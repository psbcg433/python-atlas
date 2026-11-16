"""Unit 5.3 — asyncio Internals: the Event Loop (with Lab 5.3)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = r'''
import asyncio
import dis
import errno
import gc
import heapq
import importlib.util
import inspect
import itertools
import os
import platform
import re
import select
import selectors
import shutil
import socket
import subprocess
import sys
import sysconfig
import textwrap
import threading
import time
import tracemalloc
import warnings
from collections import deque
from collections.abc import Callable, Coroutine, Generator, Iterable
from pathlib import Path
from typing import Any

DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))  # the one knob for workload sizes
REPO_ROOT = find_repo_root()
scratch_dir = REPO_ROOT / "notebooks" / "_scratch"  # git-ignored
PHASE5_DIR = scratch_dir / "phase5"
PHASE5_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(REPO_ROOT / "notebooks")
CHILD_ENV = {**os.environ, "PYTHON_COLORS": "0", "PYTHONUNBUFFERED": "1"}
HAS_RESOURCE = importlib.util.find_spec("resource") is not None  # POSIX only


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


KERNEL_LOOP = asyncio.get_running_loop()  # the kernel's own loop: top-level await runs on it
print(interpreter_label())
print(f"{DEMO_SCALE=}  kernel loop: {type(KERNEL_LOOP).__name__}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 5.3 — asyncio Internals: the Event Loop

            **Objectives**

            - Explain why one thread can serve thousands of connections (the C10k problem)
              and what "non-blocking" means at the operating-system level.
            - Use `select`, `epoll` and the `selectors` module directly.
            - Build a working event loop from scratch: generators as tasks, a ready queue,
              a timer heap and `selectors` for I/O, then an echo server on top of it.
            - Read asyncio's real loop (`_run_once`) and map every part of the toy loop onto it.
            - Explain coroutines, awaitables, Futures and Tasks, and exactly what `await` does.
            - Predict the order in which callbacks and coroutines run, in Python and in Node,
              and explain every difference.

            **JS bridge**

            | Node.js | asyncio | The difference that bites |
            | --- | --- | --- |
            | The event loop starts by itself when the script ends | You start it: `asyncio.run(main())` (Jupyter already runs one) | No loop, no async; and one loop per thread |
            | Calling an `async function` runs its body up to the first `await` | Calling an `async def` returns a coroutine object; **nothing runs** | Forgetting `await` silently does nothing (plus a warning) |
            | `Promise` | `asyncio.Future` (a result slot with callbacks); `asyncio.Task` drives a coroutine | Futures and Tasks can be **cancelled** |
            | Microtask queue (`then`, `await`) drained after every callback | One FIFO ready queue for every callback and task step | No "microtasks run first" rule (5.3.9) |
            | `setTimeout(fn, ms)` / `setImmediate(fn)` | `loop.call_later(seconds, fn)` / `loop.call_soon(fn)` | Seconds, not milliseconds |
            | libuv thread pool (4 threads) for `fs`, `dns.lookup`, `crypto` | The loop's default `ThreadPoolExecutor` (`asyncio.to_thread`) | Python's pool is bigger (`min(32, cpus + 4)`) and you call it explicitly |
            | Every `await` is a trip through the microtask queue | `await` of a coroutine that never suspends **does not yield** | A loop of quick awaits can starve other tasks |

            **How this unit runs.** The Jupyter kernel already runs an asyncio event loop,
            so cells use **top-level `await`** directly. `asyncio.run()` cannot be called
            inside a running loop (5.3.8 shows the error), so demos of `asyncio.run()`,
            `asyncio.Runner` and script entry points run as scripts in a child interpreter
            with `run_child()`. The toy event loop in 5.3.3 is plain synchronous Python and
            runs anywhere.
            """
        ),
        md(
            """
            Unit setup, part 1: imports, `DEMO_SCALE`, the scratch folder for child
            scripts, and the error and interpreter helpers used since Phase 3.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            Unit setup, part 2: `Timer` (Unit 1.14), `run_child()` (Unit 5.1; this
            version also hides memory addresses, which asyncio prints in debug messages)
            and `KERNEL_LOOP`, the loop the kernel runs cells on.
            """
        ),
        code(UNIT_SETUP_SOURCE_2),
    ]


def _why_async_cells() -> list[NotebookNode]:
    """5.3.1 Why async."""
    return [
        md(
            """
            ### 5.3.1 Why async

            **The C10k problem.** In 1999 Dan Kegel asked how one server could handle ten
            thousand clients at once. The classic design, one thread (or process) per
            connection, runs out of memory and drowns in context switches long before
            that: each thread reserves a stack, and most of those threads are just
            *waiting* for a slow client. The fix that every modern server uses (nginx,
            Node.js, asyncio, Go's runtime) is to stop dedicating a thread to each wait:

            | Model | One connection costs | Who switches between connections |
            | --- | --- | --- |
            | Thread per connection | a thread: a stack reservation (8 MiB virtual by default on Linux) + kernel bookkeeping | the OS scheduler, at any instruction (preemptive) |
            | Event loop (asyncio, Node) | a small object: a coroutine frame and a socket | the program, only at `await` (cooperative) |

            The next cell compares the two costs on this machine: the stack size the OS
            reserves for every new thread, and the memory `tracemalloc` sees for each
            parked asyncio task.
            """
        ),
        code(
            '''
            if HAS_RESOURCE:
                import resource

                stack_soft_limit, _ = resource.getrlimit(resource.RLIMIT_STACK)
                print(f"thread stack reservation: {stack_soft_limit / 2**20:.0f} MiB of virtual memory")
            else:
                print("resource module not available on this OS: skipping the stack-size probe")


            async def idle_connection(closed: asyncio.Event) -> None:
                """A connection that waits for its client: it holds no thread while waiting."""
                await closed.wait()


            task_count = 10_000 * DEMO_SCALE
            closed = asyncio.Event()
            tracemalloc.start()
            idle_tasks = [asyncio.create_task(idle_connection(closed)) for _ in range(task_count)]
            await asyncio.sleep(0)  # let every task start and park on the event
            traced_bytes, _ = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            closed.set()
            await asyncio.gather(*idle_tasks)
            print(f"{task_count:,} parked tasks: about {traced_bytes / task_count:,.0f} bytes each")
            '''
        ),
        md(
            """
            Thousands of waiting tasks cost a few megabytes in total; the same number of
            threads would reserve tens of gigabytes of address space and make the OS
            schedule all of them. (Numbers vary by Python version and OS.)

            **Blocking vs non-blocking I/O.** A *blocking* call (`time.sleep`,
            `socket.recv` on a normal socket, `requests.get`) parks the whole thread until
            the data arrives. A *non-blocking* call returns at once: either with data or
            with "not ready yet". An event loop only makes non-blocking calls, and asks the
            OS to tell it when something becomes ready. Here are twenty 50 ms waits, done
            blocking (one after another) and non-blocking (all waiting at once on one
            thread):
            """
        ),
        code(
            '''
            def blocking_fetch(seconds: float) -> None:
                """Stand-in for a blocking network call: the thread can do nothing else."""
                time.sleep(seconds)


            async def non_blocking_fetch(seconds: float) -> None:
                """The same wait, but the loop can run other tasks meanwhile."""
                await asyncio.sleep(seconds)


            request_count, wait_seconds = 20, 0.05
            with Timer(f"{request_count} blocking waits, one after another") as blocking:
                for _ in range(request_count):
                    blocking_fetch(wait_seconds)
            with Timer(f"{request_count} non-blocking waits on one thread") as non_blocking:
                await asyncio.gather(*(non_blocking_fetch(wait_seconds) for _ in range(request_count)))
            print(f"ratio: {blocking.elapsed_seconds / non_blocking.elapsed_seconds:.1f}x")
            '''
        ),
        md(
            """
            The same difference at the socket level. `socket.socketpair()` gives two
            connected sockets. On a blocking socket `recv` waits (here a 0.2 s timeout
            stops it); after `setblocking(False)` it returns immediately with
            `BlockingIOError` (errno `EAGAIN`: "try again later") when there is no data.
            """
        ),
        code(
            """
            sending_side, receiving_side = socket.socketpair()
            receiving_side.settimeout(0.2)  # blocking, but give up after 0.2 s
            started = time.perf_counter()
            try:
                receiving_side.recv(1024)
            except TimeoutError:
                print(f"blocking recv waited {time.perf_counter() - started:.2f} s for nothing")

            receiving_side.setblocking(False)
            try:
                receiving_side.recv(1024)
            except BlockingIOError as error:
                print(f"non-blocking recv returned at once: {errno.errorcode[error.errno]}")

            sending_side.send(b"order 42 ready")
            print(f"after send: {receiving_side.recv(1024)=}")
            sending_side.close()
            receiving_side.close()
            """
        ),
        md(
            """
            **Cooperative multitasking.** Threads are *preemptive*: the OS can switch at
            any moment. asyncio tasks are *cooperative*: a task runs until it reaches an
            `await` that actually suspends, and only then can another task run. A task
            that never awaits keeps everyone else waiting. Notice how `greedy` runs all
            its steps in one go while the two polite tasks take turns:
            """
        ),
        code(
            '''
            switch_trace: list[str] = []


            async def polite(name: str, steps: int) -> None:
                """Yield to the loop after every step: other tasks get a turn."""
                for step in range(steps):
                    switch_trace.append(f"{name}{step}")
                    await asyncio.sleep(0)  # the only place a switch can happen


            async def greedy(name: str, steps: int) -> None:
                """Never awaits: nobody else runs until it returns."""
                for step in range(steps):
                    switch_trace.append(f"{name}{step}")


            await asyncio.gather(polite("p", 3), greedy("g", 3), polite("q", 3))
            print(" ".join(switch_trace))
            '''
        ),
        md(
            """
            > **Note:** cooperative scheduling is why async code needs no locks around
            > `counter += 1` *between* awaits, and also why one slow, CPU-heavy or blocking
            > call freezes every connection on the loop (Unit 5.4.6 shows how to detect it).
            """
        ),
    ]


def _os_foundation_cells() -> list[NotebookNode]:
    """5.3.2 OS foundations."""
    return [
        md(
            """
            ### 5.3.2 OS foundations

            An event loop needs two things from the operating system: **non-blocking
            sockets** (calls that return "not ready" instead of waiting) and a way to
            **wait for many sockets at once**. The second comes in two styles:

            | OS | API | Style | asyncio uses |
            | --- | --- | --- | --- |
            | Any POSIX, Windows (sockets only) | `select()` | readiness: "tell me which sockets are ready"; scans every socket each call | `SelectSelector` (fallback) |
            | POSIX | `poll()` | readiness; no 1024-descriptor limit, still a scan | `PollSelector` |
            | Linux | `epoll` | readiness; the kernel keeps the interest list, cost grows with *ready* sockets only | `EpollSelector` (default on Linux) |
            | macOS, BSD | `kqueue` | readiness; also files, signals, timers | `KqueueSelector` |
            | Windows | IOCP | **completion**: "do this read and tell me when it is done" | `ProactorEventLoop` (the default on Windows) |

            Readiness APIs say *a read would not block now*; the program then does the
            read. Completion APIs do the read for you and report when it has finished.
            Node's libuv wraps the same calls (`epoll`, `kqueue`, IOCP). Which ones does
            this machine have?
            """
        ),
        code(
            """
            for api_name in ("select", "poll", "epoll", "kqueue", "devpoll"):
                status = "available" if hasattr(select, api_name) else "missing"
                print(f"select.{api_name:<8} {status}")
            print(f"selectors.DefaultSelector -> {selectors.DefaultSelector.__name__}")
            print(f"kernel loop selector: {type(KERNEL_LOOP._selector).__name__}")  # CPython internal
            print(f"{sys.platform=} (on win32 the default loop is ProactorEventLoop, using IOCP)")
            """
        ),
        md(
            """
            `select.select(readable, writable, errors, timeout)` is the oldest form: give
            it lists of sockets, get back the ones that are ready. With `timeout=0` it only
            checks; with `None` it waits until something is ready.
            """
        ),
        code(
            """
            reader_socket, writer_socket = socket.socketpair()
            readable, _, _ = select.select([reader_socket], [], [], 0)
            print(f"before send: {len(readable)} readable socket(s)")
            writer_socket.send(b"ping")
            readable, writable, _ = select.select([reader_socket], [writer_socket], [], 0)
            print(f"after send: {len(readable)} readable, {len(writable)} writable")
            print(f"data: {reader_socket.recv(16)!r}")
            reader_socket.close()
            writer_socket.close()
            """
        ),
        md(
            """
            The `selectors` module wraps all of these behind one interface and picks the
            best one (`DefaultSelector`). Each registration carries a `data` payload,
            usually the callback or task to wake up: exactly what an event loop needs. Here
            three "connections" are registered and two of them receive data:
            """
        ),
        code(
            """
            selector = selectors.DefaultSelector()
            pairs = {label: socket.socketpair() for label in ("orders", "payments", "emails")}
            for label, (receiving, _) in pairs.items():
                receiving.setblocking(False)
                selector.register(receiving, selectors.EVENT_READ, data=label)

            pairs["orders"][1].send(b"new order #7")
            pairs["emails"][1].send(b"welcome mail")
            ready = selector.select(timeout=0)  # [(SelectorKey, event mask), ...]
            for key, events in sorted(ready, key=lambda item: item[0].data):
                print(f"{key.data:<9} ready (events={events}): {key.fileobj.recv(64)!r}")
            print(f"registered: {sorted(key.data for key in selector.get_map().values())}")
            print(f"{selectors.EVENT_READ=} {selectors.EVENT_WRITE=}")
            for receiving, sending in pairs.values():
                selector.unregister(receiving)
                receiving.close()
                sending.close()
            """
        ),
        md(
            """
            **Write readiness is backpressure at the OS level.** A fresh socket is
            writable: the kernel has buffer space. Keep sending without the other side
            reading and the buffer fills; `send` then raises `BlockingIOError` and the
            socket stops being writable until the reader drains it. asyncio's
            `writer.drain()` (Unit 5.4) is built on exactly this signal.
            """
        ),
        code(
            """
            fast_sender, slow_reader = socket.socketpair()
            fast_sender.setblocking(False)
            slow_reader.setblocking(False)
            write_selector = selectors.DefaultSelector()
            write_selector.register(fast_sender, selectors.EVENT_WRITE)
            print(f"fresh socket writable: {bool(write_selector.select(timeout=0))}")

            buffered_bytes = 0
            try:
                while True:
                    buffered_bytes += fast_sender.send(b"x" * 4096)
            except BlockingIOError:
                print(f"the kernel buffered {buffered_bytes:,} bytes, then send raised BlockingIOError")
            print(f"writable while full: {bool(write_selector.select(timeout=0))}")

            drained_bytes = 0
            try:
                while True:
                    drained_bytes += len(slow_reader.recv(65536))
            except BlockingIOError:
                pass
            writable_again = bool(write_selector.select(timeout=0))
            print(f"reader drained {drained_bytes:,} bytes; writable again: {writable_again}")
            write_selector.close()
            fast_sender.close()
            slow_reader.close()
            """
        ),
        md(
            """
            **Non-blocking connect.** Even connecting can wait (a TCP handshake to a far
            server). On a non-blocking socket, `connect_ex` returns at once, usually with
            `EINPROGRESS`; the socket becomes **writable** when the handshake finishes,
            and `SO_ERROR` tells whether it succeeded. (On loopback the handshake may
            already be done, so you may see `0`.)
            """
        ),
        code(
            """
            listener = socket.create_server(("127.0.0.1", 0))  # port 0: any free port
            port = listener.getsockname()[1]
            client = socket.socket()
            client.setblocking(False)
            result_code = client.connect_ex(("127.0.0.1", port))
            print(f"connect_ex returned {errno.errorcode.get(result_code, result_code)}")

            connect_selector = selectors.DefaultSelector()
            connect_selector.register(client, selectors.EVENT_WRITE)
            connect_selector.select(timeout=1)  # wait until writable = handshake finished
            print(f"SO_ERROR after the handshake: {client.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)}")
            connection, address = listener.accept()
            print(f"server accepted a connection from {address[0]} (the client port varies)")
            for item in (connect_selector, client, connection, listener):
                item.close()
            """
        ),
    ]


def _toy_loop_cells_part_1() -> list[NotebookNode]:
    """5.3.3 A toy event loop from scratch: steps 1-3."""
    return [
        md(
            """
            ### 5.3.3 A toy event loop from scratch

            The best way to understand asyncio is to build a small one. We use **plain
            generators** as tasks (Unit 1.13): a generator runs until `yield`, hands a
            value to whoever called `send()`, and waits there until it is resumed. That is
            all a coroutine is. The loop grows in five steps, each a subclass of the last:

            | Step | Class | A task can yield | New machinery |
            | --- | --- | --- | --- |
            | 1 | `RoundRobinLoop` | anything ("let others run") | a **ready queue** (`deque`) |
            | 2 | `TimerLoop` | `("sleep", seconds)` | a **timer heap** (`heapq`) |
            | 3 | `IOLoop` | `("read", sock)`, `("write", sock)` | a **selector** |
            | 4 | (same loop) | `yield from recv(...)` | helpers composed with `yield from`, and an echo server |
            | 5 | `ToyLoop` | `("join", task)` | **tasks** with results and waiters |

            **Step 1: round-robin.** The ready queue holds `(task, value to send)` pairs.
            `run_ready()` resumes only the tasks that were ready when the pass began;
            anything scheduled during the pass waits for the next one. asyncio does the
            same (`ntodo = len(self._ready)`), and it is what keeps one busy task from
            starving the rest.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            Two countdown tasks share the loop. Each `yield` hands control back, so their
            output interleaves. Nothing here is asynchronous yet: it is just turn-taking.
            """
        ),
        code(
            '''
            def countdown(label: str, count: int) -> ToyCoroutine:
                """Print a countdown, yielding to the loop after every number."""
                while count:
                    print(f"{label}{count}", end=" ")
                    yield
                    count -= 1
                return f"{label} done"


            round_robin = RoundRobinLoop()
            round_robin.spawn(countdown("A", 3))
            round_robin.spawn(countdown("B", 2))
            round_robin.run()
            print(f"\\n{round_robin.steps} steps")
            '''
        ),
        md(
            """
            **Step 2: timers.** A task that wants to sleep yields `("sleep", seconds)`.
            The loop pushes `(wake-up time, tie-breaker, task)` onto a heap, so the
            earliest timer is always at index 0 (the counter breaks ties, because
            generators cannot be compared). `run()` now has the shape of one asyncio
            iteration: work out how long it may wait, wait, move due timers to the ready
            queue, run the ready tasks.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            Three sleepers of 0.3, 0.1 and 0.2 s finish in about 0.3 s in total, in
            wake-up order, on one thread:
            """
        ),
        code(
            '''
            def sleeper(label: str, seconds: float, started: float) -> ToyCoroutine:
                """Sleep on the toy loop, then report when it woke up."""
                yield ("sleep", seconds)
                print(f"{label:<6} woke after {time.perf_counter() - started:.2f} s")
                return label


            sleep_started = time.perf_counter()
            timer_loop = TimerLoop()
            for label, seconds in (("slow", 0.3), ("fast", 0.1), ("medium", 0.2)):
                timer_loop.spawn(sleeper(label, seconds, sleep_started))
            timer_loop.run()
            print(f"total {time.perf_counter() - sleep_started:.2f} s for 0.6 s of sleeping")
            '''
        ),
        md(
            """
            **Step 3: I/O.** A task that wants to read yields `("read", sock)`. The loop
            registers the socket with a selector, using the task as the `data` payload.
            `wait_for_events` now calls `selector.select(timeout)` instead of `sleep`: it
            returns early when a socket is ready, or when the next timer is due. Each
            registration is one-shot (unregistered when it fires); a task that wants to
            read again yields again.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            A reader waits on a socket while a second task sleeps 0.1 s and then writes
            to the other end. The reader is woken by the selector, not by polling:
            """
        ),
        code(
            '''
            def read_when_ready(sock: socket.socket, started: float) -> ToyCoroutine:
                """Wait for readability, then read."""
                yield ("read", sock)
                print(f"reader got {sock.recv(64)!r} after {time.perf_counter() - started:.2f} s")


            def write_later(sock: socket.socket, delay: float) -> ToyCoroutine:
                """Sleep, then send."""
                yield ("sleep", delay)
                sock.send(b"invoice #12 paid")


            io_left, io_right = socket.socketpair()
            io_left.setblocking(False)
            io_loop = IOLoop()
            io_loop.spawn(read_when_ready(io_left, time.perf_counter()))
            io_loop.spawn(write_later(io_right, 0.1))
            io_loop.run()
            io_left.close()
            io_right.close()
            '''
        ),
    ]


def _toy_loop_cells_part_2() -> list[NotebookNode]:
    """5.3.3 steps 4-5, and the mapping onto asyncio."""
    return [
        md(
            """
            **Step 4: an echo server.** First two helpers that wait and then act, the toy
            versions of `await sock.recv()` and `await sock.sendall()`. A task calls them
            with `yield from`, which passes every request up to the loop and returns the
            helper's result. `yield from` is the direct ancestor of `await` (PEP 380, then
            PEP 492).
            """
        ),
        code(
            '''
            def recv(sock: socket.socket, size: int) -> Generator[object, object, bytes]:
                """Wait until sock is readable, then read: a toy `await sock.recv(size)`."""
                yield ("read", sock)
                return sock.recv(size)


            def sendall(sock: socket.socket, data: bytes) -> Generator[object, object]:
                """Send everything, waiting for writability whenever the buffer is full."""
                while data:
                    yield ("write", sock)
                    data = data[sock.send(data) :]
            '''
        ),
        md(
            """
            The server task accepts connections (a listening socket is *readable* when a
            client is waiting) and spawns a handler task per client. Each handler echoes
            what it receives in upper case until the client closes (`recv` returns
            `b""`). Each client connects without blocking, sends two messages and reads
            the replies.
            """
        ),
        code(
            '''
            def echo_server(loop: IOLoop, listener: socket.socket, client_count: int) -> ToyCoroutine:
                """Accept client_count connections, one handler task each."""
                for _ in range(client_count):
                    yield ("read", listener)
                    connection, _ = listener.accept()
                    connection.setblocking(False)
                    loop.spawn(echo_handler(connection))
                listener.close()


            def echo_handler(connection: socket.socket) -> ToyCoroutine:
                """Echo in upper case until the client closes its end."""
                while data := (yield from recv(connection, 1024)):
                    yield from sendall(connection, data.upper())
                connection.close()


            def echo_client(
                port: int, name: str, messages: list[str], replies: dict[str, list[str]]
            ) -> ToyCoroutine:
                """Connect without blocking, send each message, collect the echo."""
                sock = socket.socket()
                sock.setblocking(False)
                sock.connect_ex(("127.0.0.1", port))
                yield ("write", sock)  # writable = connected
                for message in messages:
                    yield from sendall(sock, f"{name}: {message}".encode())
                    replies[name].append((yield from recv(sock, 1024)).decode())
                    yield ("sleep", 0.01)
                sock.close()
            '''
        ),
        md(
            """
            One loop, one thread: a server, two handlers and two clients all make progress
            together.
            """
        ),
        code(
            """
            echo_listener = socket.create_server(("127.0.0.1", 0))
            echo_listener.setblocking(False)
            echo_port = echo_listener.getsockname()[1]
            echo_replies: dict[str, list[str]] = {"asha": [], "ben": []}
            echo_loop = IOLoop()
            echo_loop.spawn(echo_server(echo_loop, echo_listener, client_count=2))
            echo_loop.spawn(echo_client(echo_port, "asha", ["hi", "two chai"], echo_replies))
            echo_loop.spawn(echo_client(echo_port, "ben", ["hello", "one coffee"], echo_replies))
            with Timer("echo session"):
                echo_loop.run()
            for name, replies in echo_replies.items():
                print(f"{name}: {replies}")
            print(f"about {echo_loop.steps} task steps, all on {threading.current_thread().name}")
            """
        ),
        md(
            """
            **Step 5: tasks with results.** So far a task's return value is lost, and no
            task can wait for another. `ToyLoop.spawn` returns a `ToyTask` holding the
            result and a list of *waiters*. A task yields `("join", other_task)`; if the
            other task has finished it is resumed at once with the result, otherwise it is
            parked in `waiters` until `finish()` puts it back on the ready queue, with
            the result as the value to send in. That is a Future with done-callbacks, and
            `send(result)` is how `await task` gets its value.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            A checkout task starts a price lookup in the background, does its own 0.1 s
            of work meanwhile, then joins the lookup. Both waits overlap:
            """
        ),
        code(
            '''
            def price_lookup(sku: str, seconds: float) -> ToyCoroutine:
                """Pretend to call a pricing service."""
                yield ("sleep", seconds)
                return {"chai": 20, "samosa": 15}[sku]


            def checkout(loop: ToyLoop, sku: str, quantity: int) -> ToyCoroutine:
                """Overlap our own work with a background lookup, then join it."""
                lookup = loop.spawn(price_lookup(sku, 0.15))
                yield ("sleep", 0.1)  # validate the cart meanwhile
                unit_price = yield ("join", lookup)
                return f"{quantity} x {sku} = Rs {unit_price * quantity}"


            toy_loop = ToyLoop()
            with Timer("checkout (0.1 s + 0.15 s of waiting)"):
                checkout_task = toy_loop.spawn(checkout(toy_loop, "chai", 3))
                toy_loop.run()
            print(f"{checkout_task.done=} {checkout_task.result=}")
            '''
        ),
        md(
            """
            #### How asyncio's real loop maps onto the toy loop

            asyncio's loop lives in `asyncio/base_events.py` (`BaseEventLoop`) and
            `asyncio/selector_events.py`; it is pure Python, while `Task` and `Future`
            are implemented in C (`_asyncio`) for speed.

            | Toy loop | asyncio | Difference |
            | --- | --- | --- |
            | `self.ready`: deque of `(task, value)` | `loop._ready`: deque of `Handle` (a callback + arguments) | asyncio queues *callbacks*; resuming a Task is just one kind of callback |
            | `self.timers`: heap of `(when, n, task)` | `loop._scheduled`: heap of `TimerHandle` | cancelled timers are dropped lazily |
            | `self.selector` | `loop._selector` (`EpollSelector` here) | the payload is a reader/writer callback |
            | one pass of `TimerLoop.run()` | `loop._run_once()` | same order: timeout → `select` → due timers → run `ntodo` handles |
            | `yield ("sleep", s)` | `await asyncio.sleep(s)`: a Future + `loop.call_later(s, ...)` that resolves it | |
            | `yield ("read", sock)` | `await loop.sock_recv(sock, n)`: `loop.add_reader(fd, callback)` | streams and transports wrap this |
            | `yield from helper()` | `await coroutine()` | `await` also accepts Futures and `__await__` objects |
            | `ToyTask`, `waiters` | `asyncio.Task`, a Future's done-callbacks | |
            | `coroutine.send(value)` in `run_ready` | `Task.__step()` calls `coro.send(None)` | the result is read from the Future, not sent in |
            | `yield ("join", task)` | `await task` | |

            The kernel's loop is a real instance; its private attributes are visible
            (CPython internals: fine to look at, never rely on them in code):
            """
        ),
        code(
            """
            print(f"loop class: {' -> '.join(cls.__name__ for cls in type(KERNEL_LOOP).__mro__[:4])}")
            ready, scheduled, selector = KERNEL_LOOP._ready, KERNEL_LOOP._scheduled, KERNEL_LOOP._selector
            print(f"_ready:     {type(ready).__name__} of Handle, {len(ready)} queued now")
            print(f"_scheduled: {type(scheduled).__name__} heap of TimerHandle, {len(scheduled)} now")
            print(f"_selector:  {type(selector).__name__} watching {len(selector.get_map())} descriptors")
            print(f"Task implemented in: {asyncio.Task.__module__}  Future in: {asyncio.Future.__module__}")
            """
        ),
        md(
            """
            And the heart of `_run_once`, filtered to the lines that match the toy loop's
            steps (the full method is about 100 lines; read it with
            `inspect.getsource(asyncio.base_events.BaseEventLoop._run_once)`):
            """
        ),
        code(
            """
            run_once_lines = inspect.getsource(asyncio.base_events.BaseEventLoop._run_once).splitlines()
            keywords = (
                "heapq.heappop",
                "timeout =",
                "_selector.select",
                "_process_events",
                "ntodo",
                "popleft",
                "_run()",
            )
            for line_number, line in enumerate(run_once_lines, start=1):
                if any(keyword in line for keyword in keywords):
                    print(f"{line_number:3} {line.rstrip()}")
            """
        ),
    ]


def _native_coroutine_cells() -> list[NotebookNode]:
    """5.3.4 Native coroutines."""
    return [
        md(
            """
            ### 5.3.4 Native coroutines

            `async def` defines a **coroutine function**. Calling it does **not** run the
            body: it returns a *coroutine object*, a paused frame waiting for someone to
            drive it. In JavaScript, calling an `async function` runs the body
            immediately, up to the first `await`. Watch for the missing body print:
            """
        ),
        code(
            '''
            async def fetch_price(sku: str) -> int:
                """Pretend to look up a price."""
                print(f"  fetch_price({sku!r}) body runs")
                await asyncio.sleep(0)
                return 250


            price_coroutine = fetch_price("chai")
            print(
                f"called: {type(price_coroutine).__name__}, state {inspect.getcoroutinestate(price_coroutine)}"
            )
            print(f"{inspect.iscoroutinefunction(fetch_price)=} {inspect.iscoroutine(price_coroutine)=}")
            chai_price = await price_coroutine  # now it runs
            print(f"awaited: {chai_price=}, state {inspect.getcoroutinestate(price_coroutine)}")
            '''
        ),
        md(
            """
            A coroutine that is created and dropped without ever being awaited is almost
            always a bug (a forgotten `await`). CPython warns when such a coroutine is
            garbage-collected. The warning is captured here instead of printed:
            """
        ),
        code(
            """
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                forgotten = fetch_price("samosa")  # BUG: no await
                del forgotten  # last reference gone: the coroutine is destroyed unstarted
                gc.collect()
            for caught in caught_warnings:
                print(f"{caught.category.__name__}: {caught.message}")
            """
        ),
        md(
            """
            **Awaitables.** `await x` accepts three kinds of object:

            | Awaitable | What it is | Made by |
            | --- | --- | --- |
            | coroutine | the object an `async def` call returns | calling a coroutine function |
            | `asyncio.Future` | a result slot that callbacks can wait on | `loop.create_future()` |
            | `asyncio.Task` | a Future that drives a coroutine | `asyncio.create_task(coro)` |
            | any object with `__await__` | `__await__()` must return an iterator (usually a generator) | your own class |

            A generator is *not* awaitable (unless decorated by the legacy
            `types.coroutine`). `Delay` below is a custom awaitable: its `__await__`
            delegates to `asyncio.sleep`'s own `__await__` with `yield from`.
            """
        ),
        code(
            '''
            class Delay:
                """A custom awaitable: __await__ returns a generator."""

                def __init__(self, seconds: float) -> None:
                    self.seconds = seconds

                def __await__(self) -> Generator[Any, None, str]:
                    yield from asyncio.sleep(self.seconds).__await__()
                    return f"waited {self.seconds} s"


            bare_future = KERNEL_LOOP.create_future()
            bare_future.set_result("ready")
            candidates = {
                "coroutine": asyncio.sleep(0, result="slept"),
                "Task": asyncio.create_task(asyncio.sleep(0, result="task done")),
                "Future": bare_future,
                "Delay(0.01)": Delay(0.01),
            }
            for label, candidate in candidates.items():
                print(f"{label:<12} isawaitable={inspect.isawaitable(candidate)}  result={await candidate!r}")
            plain_generator = (number for number in range(1))
            print(f"{'generator':<12} isawaitable={inspect.isawaitable(plain_generator)}")
            '''
        ),
        md(
            """
            **Under the hood.** A coroutine is compiled like a generator. `dis` shows
            `RETURN_GENERATOR` (calling the function only builds the object), and each
            `await` becomes `GET_AWAITABLE` followed by a `SEND` / `YIELD_VALUE` loop:
            the same machinery as `yield from`. The `CO_COROUTINE` flag marks the code
            object.
            """
        ),
        code(
            '''
            async def two_steps() -> int:
                """One await, then a return."""
                first = await asyncio.sleep(0, result=1)
                return first + 1


            interesting = {
                "RETURN_GENERATOR",
                "GET_AWAITABLE",
                "SEND",
                "YIELD_VALUE",
                "END_SEND",
                "RETURN_VALUE",
            }
            print(
                [
                    instruction.opname
                    for instruction in dis.get_instructions(two_steps)
                    if instruction.opname in interesting
                ]
            )
            print(f"{bool(two_steps.__code__.co_flags & inspect.CO_COROUTINE)=}")
            print(f"{bool(countdown.__code__.co_flags & inspect.CO_GENERATOR)=}  (the toy-loop generator)")
            '''
        ),
        md(
            """
            **Driving a coroutine with `send`.** Nothing about `async def` needs asyncio.
            `coroutine.send(value)` runs it until something deep inside yields; the
            yielded value comes out of `send`, and the next `send(reply)` resumes it with
            `reply` as the result of that innermost `yield`. Here `Ask` yields a question
            out to whoever drives the coroutine, and we answer by hand, exactly as an
            event loop would:
            """
        ),
        code(
            '''
            class Ask:
                """An awaitable that hands a question to the driver and returns its reply."""

                def __init__(self, question: str) -> None:
                    self.question = question

                def __await__(self) -> Generator[str, object, object]:
                    reply = yield self.question
                    return reply


            async def quote_order(sku: str, quantity: int) -> str:
                """Needs two answers from outside before it can finish."""
                unit_price = await Ask(f"price of {sku}?")
                gst_percent = await Ask("GST rate?")
                total = unit_price * quantity * (100 + gst_percent) / 100
                return f"{quantity} x {sku} = Rs {total:.2f}"


            quote = quote_order("chai", 3)
            print(f"{quote.send(None)=}")  # start: run to the first await
            print(f"{quote.send(20)=}")  # answer the price; get the next question
            try:
                quote.send(18)  # answer the GST rate; the coroutine returns
            except StopIteration as stop:
                print(f"finished with {stop.value!r}")
            print(f"{inspect.getcoroutinestate(quote)=}")
            '''
        ),
        md(
            """
            `throw(error)` resumes the coroutine by raising `error` at the suspended
            `await` (this is how cancellation is delivered: the loop throws
            `CancelledError` in). `close()` throws `GeneratorExit`, running `finally`
            blocks.
            """
        ),
        code(
            '''
            async def guarded_quote() -> str:
                """Falls back when the price lookup fails."""
                try:
                    return f"price {await Ask('price?')}"
                except LookupError as error:
                    return f"fallback price ({type(error).__name__}: {error})"
                finally:
                    print("  guarded_quote cleanup ran")


            first_quote = guarded_quote()
            first_quote.send(None)
            try:
                first_quote.throw(KeyError("unknown sku"))
            except StopIteration as stop:
                print(f"after throw: {stop.value!r}")

            second_quote = guarded_quote()
            second_quote.send(None)
            second_quote.close()
            print(f"after close: {inspect.getcoroutinestate(second_quote)}")
            '''
        ),
    ]


def _await_cells() -> list[NotebookNode]:
    """5.3.5 What await does."""
    return [
        md(
            """
            ### 5.3.5 What `await` does

            `await something` does three things:

            1. **Suspension up to the Task.** If `something` is a coroutine, Python runs
               it in place (no loop involved). Only when the chain reaches a Future that
               is not done yet does anything suspend: the Future's `__await__` yields
               *the Future itself*, and that yield travels up through every `await` in
               the chain to the Task that is driving the outermost coroutine.
            2. **Future callbacks.** The Task receives the Future and registers its own
               wake-up method with `future.add_done_callback(...)`, then returns to the
               loop. The Task is now suspended; the loop runs other things.
            3. **Resumption.** When someone calls `future.set_result(value)` (a timer, an
               I/O callback, another task), the Future schedules its callbacks with
               `call_soon`. The Task's wake-up runs, calls `coro.send(None)`, execution
               continues inside the innermost `await`, and the Future's `__await__`
               returns `value`.

            ```mermaid
            sequenceDiagram
                participant Loop as Event loop
                participant Task as Task.__step
                participant Outer as outer()
                participant Inner as inner()
                participant Fut as Future
                Loop->>Task: run handle (Task step)
                Task->>Outer: coro.send(None)
                Outer->>Inner: await inner()
                Inner->>Fut: await future
                Fut-->>Task: yield future (up through every await)
                Task->>Fut: add_done_callback(task wake-up)
                Task-->>Loop: return: the task is suspended
                Note over Loop: runs other callbacks, waits in select()
                Loop->>Fut: set_result(42) from a timer or I/O callback
                Fut->>Loop: call_soon(task wake-up)
                Loop->>Task: wake-up, then __step
                Task->>Outer: coro.send(None)
                Outer->>Inner: resumes inside inner()
                Fut-->>Inner: __await__ returns 42
                Inner-->>Outer: return 42
                Outer-->>Task: StopIteration(value)
                Task->>Task: set_result(value), schedule its own callbacks
            ```

            <details><summary>ASCII version of the diagram</summary>

            ```text
            Loop        Task.__step       outer()        inner()        Future
             | run step     |                |              |              |
             |------------->| send(None)     |              |              |
             |              |--------------->| await inner()|              |
             |              |                |------------->| await future |
             |              |<---------------- yield future (travels up) --|
             |              | add_done_callback(wakeup) ------------------>|
             |<-------------| return (suspended)                           |
             |  ... other callbacks, select() ...                          |
             |---------------------------------------- set_result(42) ---->|
             |<------------------------------------- call_soon(wakeup) ----|
             |------------->| send(None)     |              |              |
             |              |--------------->|------------->| gets 42 <----|
             |              |<-- StopIteration(value) ------| return 42    |
             |              | set_result(value) on the Task                |
            ```

            </details>

            The first claim can be checked directly: drive a coroutine that awaits a
            Future, and the object that comes out of `send` *is* that Future.
            """
        ),
        code(
            '''
            async def wait_for_payment(payment: asyncio.Future[str]) -> str:
                """Suspend until the payment Future has a result."""
                receipt = await payment
                return f"paid: {receipt}"


            payment = KERNEL_LOOP.create_future()
            payment_coroutine = wait_for_payment(payment)
            yielded = payment_coroutine.send(None)
            print(f"{yielded is payment=}: the Future itself came out of the coroutine")
            payment.set_result("UPI-7781")
            try:
                payment_coroutine.send(None)
            except StopIteration as stop:
                print(f"resumed, and the coroutine returned {stop.value!r}")
            '''
        ),
        md(
            """
            Through a chain of coroutines the Future still comes out at the top, and
            every frame in between stays suspended. `cr_await` shows what each
            suspended coroutine is waiting on (the innermost one waits on the
            Future's iterator, `FutureIter`):
            """
        ),
        code(
            """
            async def inner(future: asyncio.Future[int]) -> int:
                return await future


            async def middle(future: asyncio.Future[int]) -> int:
                return await inner(future) * 2


            async def outer(future: asyncio.Future[int]) -> int:
                return await middle(future) + 1


            chain_future = KERNEL_LOOP.create_future()
            chain = outer(chain_future)
            print(f"{chain.send(None) is chain_future=}")
            link: object = chain
            while inspect.iscoroutine(link):
                line_number, waiting_on = link.cr_frame.f_lineno, type(link.cr_await).__name__
                print(f"  {link.__qualname__:<6} suspended at line {line_number}, awaiting {waiting_on}")
                link = link.cr_await
            chain_future.set_result(20)
            try:
                chain.send(None)
            except StopIteration as stop:
                print(f"{stop.value=}  (20 * 2 + 1)")
            """
        ),
        md(
            """
            **Future callbacks are scheduled, never called inline.** `set_result` puts
            each done-callback on the ready queue with `call_soon`; they run on the next
            loop iteration. (JS behaves similarly: `.then` callbacks are queued as
            microtasks.)
            """
        ),
        code(
            """
            order_ready = KERNEL_LOOP.create_future()
            order_ready.add_done_callback(lambda future: print(f"  callback ran with {future.result()!r}"))
            order_ready.set_result("order 17")
            print("set_result returned; the callback has not run yet")
            await asyncio.sleep(0)  # one trip through the loop
            print("after one loop iteration")
            """
        ),
        md(
            """
            Now with a real Task. While suspended, the Task remembers the Future it waits
            on (`_fut_waiter`, a CPython internal), and the Future holds the Task's
            wake-up callback. `asyncio.capture_call_graph()` (*new in 3.14*) shows the
            same chain from the outside, as `python -m asyncio pstree <pid>` does for a
            running program.
            """
        ),
        code(
            """
            async def courier(parcel: asyncio.Future[str]) -> str:
                return f"delivered {await parcel}"


            async def shop(parcel: asyncio.Future[str]) -> str:
                return await courier(parcel)


            parcel = KERNEL_LOOP.create_future()
            shop_task = asyncio.create_task(shop(parcel), name="shop-task")
            await asyncio.sleep(0)  # let the task start and suspend
            print(f"{shop_task._fut_waiter is parcel=}  callbacks on the Future: {len(parcel._callbacks)}")
            if sys.version_info >= (3, 14):
                graph = asyncio.capture_call_graph(shop_task)
                frame_names = [entry.frame.f_code.co_name for entry in graph.call_stack]
                print(f"call graph of {graph.future.get_name()}: {frame_names}")
            else:
                print("asyncio.capture_call_graph needs Python 3.14+: skipped")
            parcel.set_result("parcel #5")
            print(f"{await shop_task=}")
            """
        ),
    ]


def _asyncio_loop_cells() -> list[NotebookNode]:
    """5.3.6 The asyncio loop."""
    return [
        md(
            """
            ### 5.3.6 The asyncio loop

            asyncio's loop keeps three structures, exactly like the toy loop:

            | Structure | Attribute | Holds |
            | --- | --- | --- |
            | Ready queue | `loop._ready` | `Handle`s to run on the next iteration, FIFO |
            | Scheduled-timer heap | `loop._scheduled` | `TimerHandle`s ordered by `when` |
            | Selector | `loop._selector` | file descriptors with reader/writer callbacks |

            **One `_run_once` iteration:**

            1. Drop cancelled timers from the heap when there are many of them.
            2. Compute the select timeout: `0` if the ready queue is not empty, otherwise
               the time until the earliest timer, otherwise wait forever.
            3. `event_list = self._selector.select(timeout)`, then `_process_events`
               appends the callbacks of every ready socket to the ready queue.
            4. Pop every timer whose time has come and append it to the ready queue.
            5. Run exactly the `ntodo = len(self._ready)` handles that are queued *now*.
               Handles added while they run wait for the next iteration.

            The scheduling API maps onto those structures:

            | Method | Puts a handle on | JS analogue |
            | --- | --- | --- |
            | `loop.call_soon(callback, *args)` | ready queue | `setImmediate` |
            | `loop.call_later(delay, callback, *args)` | timer heap, `when = loop.time() + delay` | `setTimeout` (seconds, not ms) |
            | `loop.call_at(when, callback, *args)` | timer heap at an absolute loop time | — |
            | `loop.time()` | the loop's clock: `time.monotonic()` | `performance.now()` |

            The next cell schedules one of each and records when they ran:
            """
        ),
        code(
            '''
            schedule_log: list[str] = []
            loop_start = KERNEL_LOOP.time()
            all_fired = KERNEL_LOOP.create_future()


            def record(label: str) -> None:
                """Log the label with milliseconds since loop_start."""
                schedule_log.append(f"{label:<24} at +{(KERNEL_LOOP.time() - loop_start) * 1000:3.0f} ms")


            KERNEL_LOOP.call_later(0.05, record, "call_later(0.05)")
            KERNEL_LOOP.call_at(loop_start + 0.02, record, "call_at(start + 0.02)")
            KERNEL_LOOP.call_soon(record, "call_soon")
            KERNEL_LOOP.call_later(0.06, all_fired.set_result, None)
            await all_fired
            print("\\n".join(schedule_log))
            clock_gap_us = abs(KERNEL_LOOP.time() - time.monotonic()) * 1e6
            print(f"loop.time() and time.monotonic() differ by {clock_gap_us:.0f} us")
            '''
        ),
        md(
            """
            Every scheduling call returns a handle that can be cancelled before it runs.
            A `TimerHandle` also knows its `when()`:
            """
        ),
        code(
            """
            soon_handle = KERNEL_LOOP.call_soon(print, "never printed")
            timer_handle = KERNEL_LOOP.call_later(10, print, "never printed either")
            due_in = timer_handle.when() - KERNEL_LOOP.time()
            print(f"{type(soon_handle).__name__}, {type(timer_handle).__name__} due in {due_in:.2f} s")
            soon_handle.cancel()
            timer_handle.cancel()
            print(f"{soon_handle.cancelled()=} {timer_handle.cancelled()=}")
            await asyncio.sleep(0)  # the cancelled handles are skipped
            """
        ),
        md(
            """
            The ready queue is a plain `deque` of handles; their reprs name the callback.
            (The kernel may have queued handles of its own, so the next cell filters on
            our function's name, and hides the source location in the repr.)
            """
        ),
        code(
            '''
            def pack_order(order_id: str) -> None:
                """A trivial callback."""


            for order_id in ("A-1", "A-2", "A-3"):
                KERNEL_LOOP.call_soon(pack_order, order_id)
            print(
                [
                    re.sub(r" at .*>", ">", repr(handle))
                    for handle in KERNEL_LOOP._ready
                    if "pack_order" in repr(handle)
                ]
            )
            await asyncio.sleep(0)
            still_queued = sum("pack_order" in repr(handle) for handle in KERNEL_LOOP._ready)
            print(f"after one iteration: {still_queued} left")
            '''
        ),
        md(
            """
            **The selector part.** `loop.add_reader(fd, callback)` registers a file
            descriptor with the loop's selector; when `select()` reports it readable,
            `_process_events` puts the callback on the ready queue. Streams, transports
            and `sock_recv` are all built on this. Here a socket pair is watched by the
            kernel's loop:
            """
        ),
        code(
            '''
            watched_socket, peer_socket = socket.socketpair()
            watched_socket.setblocking(False)
            data_arrived = KERNEL_LOOP.create_future()


            def on_readable() -> None:
                """Called by the loop when select() reports watched_socket readable."""
                data_arrived.set_result(watched_socket.recv(64))


            KERNEL_LOOP.add_reader(watched_socket.fileno(), on_readable)
            registered = watched_socket.fileno() in KERNEL_LOOP._selector.get_map()
            print(f"registered with {type(KERNEL_LOOP._selector).__name__}: {registered}")
            KERNEL_LOOP.call_later(0.02, peer_socket.send, b"payment confirmed")
            print(f"reader callback received {await data_arrived!r}")
            KERNEL_LOOP.remove_reader(watched_socket.fileno())
            registered = watched_socket.fileno() in KERNEL_LOOP._selector.get_map()
            print(f"still registered after remove_reader: {registered}")
            watched_socket.close()
            peer_socket.close()
            '''
        ),
        md(
            """
            **Watching `_run_once` iterate.** A loop subclass can wrap `_run_once` and
            print the queue sizes at the start of each iteration. It must run as the
            *only* loop of a fresh process (the kernel's loop is busy), so it runs as a
            script with `asyncio.Runner(loop_factory=...)`. Read it as: iteration 1 runs
            `main`'s first step; later ones run task steps and callbacks; when nothing is
            ready the loop sleeps in `select()` until the next timer is due.
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import asyncio


                    class TracingLoop(asyncio.SelectorEventLoop):
                        iteration = 0

                        def _run_once(self):
                            self.iteration += 1
                            ready, timers = len(self._ready), len(self._scheduled)
                            print(f"iteration {self.iteration}: {ready=} {timers=}")
                            super()._run_once()


                    async def worker(name, delay):
                        await asyncio.sleep(delay)
                        print(f"    {name} woke up")


                    async def main():
                        asyncio.get_running_loop().call_soon(print, "    call_soon callback ran")
                        await asyncio.gather(worker("fast", 0.01), worker("slow", 0.02))
                        print("    main done")


                    with asyncio.Runner(loop_factory=TracingLoop) as runner:
                        runner.run(main())
                    """
                )
            )
            '''
        ),
        md(
            """
            The last few iterations are `Runner` shutting down (closing async generators
            and the default executor). The counts depend on timing, so they can differ
            slightly between runs.
            """
        ),
    ]


def _future_task_cells() -> list[NotebookNode]:
    """5.3.7 Futures and Tasks."""
    return [
        md(
            """
            ### 5.3.7 Futures and Tasks

            A **Future** is a slot for a result that does not exist yet, plus a list of
            callbacks to run when it arrives. A **Task** is a Future that drives a
            coroutine: its result is the coroutine's return value. You rarely create
            Futures yourself (libraries do), but every `await` that really suspends ends at
            one. The Future API, including its errors:
            """
        ),
        code(
            """
            receipt = KERNEL_LOOP.create_future()
            print(f"{receipt.done()=}  result() too early -> {raised_message(receipt.result)}")
            receipt.set_result("R-1001")
            print(f"{receipt.done()=} {receipt.result()=}")
            print(f"set_result twice -> {raised_message(lambda: receipt.set_result('R-1002'))}")

            declined = KERNEL_LOOP.create_future()
            declined.set_exception(ValueError("card declined"))
            print(f"{declined.exception()=}  result() -> {raised_message(declined.result)}")

            abandoned = KERNEL_LOOP.create_future()
            abandoned.cancel("customer left")
            try:
                abandoned.result()
            except asyncio.CancelledError as error:  # a BaseException, not an Exception
                print(f"{abandoned.cancelled()=}  result() -> CancelledError: {error}")
            print(f"{issubclass(asyncio.Task, asyncio.Future)=}")
            """
        ),
        md(
            """
            **`create_task` schedules; it does not run.** The new task's first step is put
            on the ready queue and runs the next time the current task yields to the
            loop. Give tasks names: they show up in debug messages and call graphs.
            """
        ),
        code(
            """
            task_trace: list[str] = []


            async def brew(kind: str) -> str:
                task_trace.append(f"{kind}: starts")
                await asyncio.sleep(0)
                task_trace.append(f"{kind}: done")
                return kind


            brew_task = asyncio.create_task(brew("masala chai"), name="brew-chai")
            task_trace.append(f"created {brew_task.get_name()}, done={brew_task.done()}")
            task_trace.append(f"awaited: {await brew_task!r}")
            print("\\n".join(task_trace))
            print(f"{brew_task.get_coro().__qualname__=}")
            """
        ),
        md(
            """
            **Eager tasks.** An *eager* task runs its first step synchronously inside
            `create_task`, up to the first real suspension, like a JS `async function`
            call. If the coroutine finishes without suspending (a cache hit), the task is
            complete before `create_task` returns and never touches the loop. Per task:
            `create_task(coro, eager_start=True)` (*new in 3.14*); for a whole loop:
            `loop.set_task_factory(asyncio.eager_task_factory)` (*new in 3.12*).
            """
        ),
        code(
            """
            task_trace.clear()


            async def cached_price(label: str) -> int:
                task_trace.append(f"{label}: body runs")
                return 99  # never suspends


            if sys.version_info >= (3, 14):
                lazy_task = asyncio.create_task(cached_price("lazy"))
                eager_task = asyncio.create_task(cached_price("eager"), eager_start=True)
                task_trace.append(f"after create_task: {lazy_task.done()=} {eager_task.done()=}")
                await lazy_task
                print("\\n".join(task_trace))
            else:
                print("create_task(eager_start=True) needs Python 3.14+: skipped")
            """
        ),
        md(
            """
            The eager factory pays off when most tasks finish without suspending. This
            benchmark gathers tens of thousands of cache lookups (all hits) with the
            default and the eager factory, each in a fresh loop in a child process.
            Timings vary; the ratio is the point.
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import asyncio
                    import os
                    import time

                    DEMO_SCALE = int(os.environ.get("PHASE5_DEMO_SCALE", "1"))
                    CACHE = {f"sku-{number}": number for number in range(1000)}


                    async def lookup(sku):
                        if sku in CACHE:
                            return CACHE[sku]  # cache hit: never suspends
                        await asyncio.sleep(0)
                        return -1


                    async def main():
                        skus = [f"sku-{number % 1000}" for number in range(50_000 * DEMO_SCALE)]
                        started = time.perf_counter()
                        await asyncio.gather(*(lookup(sku) for sku in skus))
                        return time.perf_counter() - started


                    timings = {}
                    factories = {"default tasks": None, "eager_task_factory": asyncio.eager_task_factory}
                    for label, factory in factories.items():
                        with asyncio.Runner() as runner:
                            runner.get_loop().set_task_factory(factory)
                            timings[label] = runner.run(main())
                        print(f"{label:<19} {timings[label]:.3f} s")
                    print(f"eager speedup: {timings['default tasks'] / timings['eager_task_factory']:.1f}x")
                    """
                )
            )
            '''
        ),
        md(
            """
            **Keep a reference to every task.** The loop holds only *weak* references to
            tasks. A fire-and-forget task waiting on something that nothing else
            references can be garbage-collected mid-flight: its `finally` runs at a
            random moment and asyncio reports "Task was destroyed but it is pending!".
            The next cell provokes it deliberately (with a temporary exception handler so
            the report is printed here instead of logged):
            """
        ),
        code(
            '''
            loop_reports: list[str] = []
            previous_handler = KERNEL_LOOP.get_exception_handler()
            KERNEL_LOOP.set_exception_handler(lambda loop, context: loop_reports.append(context["message"]))


            async def send_receipt_email() -> None:
                """Waits on a Future that only this coroutine references."""
                reply = KERNEL_LOOP.create_future()
                try:
                    await reply
                finally:
                    loop_reports.append("send_receipt_email: finally ran")


            asyncio.create_task(send_receipt_email())  # no reference kept
            await asyncio.sleep(0)  # let it start and park on its Future
            gc.collect()  # task -> coroutine -> Future -> task is an unreachable cycle
            await asyncio.sleep(0)
            KERNEL_LOOP.set_exception_handler(previous_handler)
            print("\\n".join(loop_reports))
            '''
        ),
        md(
            """
            The fix: keep tasks in a set and discard them when they finish (the pattern
            from the `asyncio.create_task` docs), or better, start them in a `TaskGroup`
            (5.4.1), which holds references for you.
            """
        ),
        code(
            '''
            background_tasks: set[asyncio.Task[None]] = set()


            def fire_and_forget(coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
                """Start a task and keep a strong reference until it finishes."""
                task = asyncio.create_task(coroutine)
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return task


            loop_reports.clear()
            kept_task = fire_and_forget(send_receipt_email())
            await asyncio.sleep(0)
            gc.collect()
            print(f"after gc: {kept_task.done()=}, {len(background_tasks)} task(s) referenced")
            kept_task.cancel()
            await asyncio.sleep(0)
            print(f"after cancel: {kept_task.cancelled()=}, {len(background_tasks)} referenced; {loop_reports}")
            '''
        ),
    ]


def _core_api_cells() -> list[NotebookNode]:
    """5.3.8 Core API."""
    return [
        md(
            """
            ### 5.3.8 Core API

            | Call | What it does |
            | --- | --- |
            | `asyncio.run(main())` | create a new loop, run `main()` to completion, cancel leftover tasks, shut down async generators and the default executor, close the loop |
            | `asyncio.Runner()` (*new in 3.11*) | the same, but several `runner.run(...)` calls share one loop; takes `debug=` and `loop_factory=` |
            | `await coro` | run `coro` inside the current task (sequential) |
            | `asyncio.create_task(coro)` | run `coro` concurrently as a new task |
            | `asyncio.gather(*aws)` | run all concurrently; results in argument order |
            | `asyncio.sleep(0)` | yield to the loop once |
            | `asyncio.wait_for(aw, timeout)` | `TimeoutError` (and cancel `aw`) if it takes too long |

            **`asyncio.run` in Jupyter.** It refuses to start a second loop inside the
            kernel's running loop. The coroutine was never started, so it is closed by
            hand to avoid the "never awaited" warning:
            """
        ),
        code(
            """
            async def main_entry() -> str:
                await asyncio.sleep(0)
                return "done"


            entry = main_entry()
            try:
                asyncio.run(entry)
            except RuntimeError as error:
                print(f"{type(error).__name__}: {error}")
            finally:
                entry.close()
            """
        ),
        md(
            """
            In a script, `asyncio.run` is the one place where sync code enters async code:
            the entry point, under the `__main__` guard. Each call builds and closes a
            fresh loop, and outside it there is no running loop:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import asyncio


                    async def fetch(name, seconds):
                        await asyncio.sleep(seconds)
                        return name


                    async def main():
                        loop = asyncio.get_running_loop()
                        print(f"inside asyncio.run: {type(loop).__name__}, debug={loop.get_debug()}")
                        return await asyncio.gather(fetch("menu", 0.05), fetch("stock", 0.05))


                    if __name__ == "__main__":
                        print(asyncio.run(main()))
                        print(asyncio.run(main(), debug=True))
                        try:
                            asyncio.get_running_loop()
                        except RuntimeError as error:
                            print(f"after asyncio.run: RuntimeError: {error}")
                    """
                )
            )
            '''
        ),
        md(
            """
            `asyncio.Runner` keeps one loop across several `run()` calls (useful for a
            sync program that calls async code at a few points, or for tests). Two
            `asyncio.run` calls get two different loops:
            """
        ),
        code(
            '''
            print(
                run_child(
                    """
                    import asyncio


                    async def current_loop():
                        return asyncio.get_running_loop()


                    with asyncio.Runner(debug=False) as runner:
                        first, second = runner.run(current_loop()), runner.run(current_loop())
                        print(f"Runner: same loop for both calls: {first is second}")
                        print(f"Runner: loop closed inside the with block: {first.is_closed()}")
                    print(f"Runner: loop closed after the with block: {first.is_closed()}")
                    shared = asyncio.run(current_loop()) is asyncio.run(current_loop())
                    print(f"two asyncio.run calls share a loop: {shared}")
                    """
                )
            )
            '''
        ),
        md(
            """
            **Sequential `await` vs `create_task` vs `gather`.** Three 0.2 s lookups.
            Awaiting them one by one takes 0.6 s; starting them as tasks first, or
            gathering them, overlaps the waits:
            """
        ),
        code(
            """
            async def fetch_menu(section: str, seconds: float = 0.2) -> str:
                await asyncio.sleep(seconds)
                return section


            sections = ["tea", "snacks", "desserts"]
            with Timer("sequential awaits") as sequential_timer:
                sequential_results = []
                for section in sections:  # one at a time
                    sequential_results.append(await fetch_menu(section))
            with Timer("create_task, then await each") as task_timer:
                menu_tasks = [asyncio.create_task(fetch_menu(section)) for section in sections]
                task_results = []
                for task in menu_tasks:  # all three are already running
                    task_results.append(await task)
            with Timer("gather") as gather_timer:
                gather_results = await asyncio.gather(*(fetch_menu(section) for section in sections))
            print(f"same results: {sequential_results == task_results == gather_results}")
            print(
                f"sequential / gather: {sequential_timer.elapsed_seconds / gather_timer.elapsed_seconds:.1f}x"
            )
            """
        ),
        md(
            """
            **`sleep(0)` and the "await does not always yield" rule.** Awaiting a
            coroutine that never reaches a pending Future runs it inline, like a normal
            function call: no other task gets a turn. `asyncio.sleep(0)` is the explicit
            "let others run" (it yields a bare `None` to the Task, which re-queues itself
            with `call_soon`). In JS, by contrast, *every* `await` goes through the
            microtask queue.
            """
        ),
        code(
            '''
            yield_trace: list[str] = []


            async def no_suspend() -> None:
                """Awaitable, but never suspends."""


            async def worker(name: str, pause: Callable[[], Coroutine[Any, Any, None]]) -> None:
                for step in range(2):
                    yield_trace.append(f"{name}{step}")
                    await pause()


            await asyncio.gather(worker("A", no_suspend), worker("B", no_suspend))
            print(f"await no_suspend():  {' '.join(yield_trace)}")
            yield_trace.clear()
            await asyncio.gather(worker("A", lambda: asyncio.sleep(0)), worker("B", lambda: asyncio.sleep(0)))
            print(f"await sleep(0):      {' '.join(yield_trace)}")
            '''
        ),
        md(
            """
            **`wait_for`** puts a timeout on one awaitable. On timeout it cancels the
            inner task (its `except CancelledError` / `finally` runs), waits for it to
            finish cancelling, then raises `TimeoutError`. `timeout=None` waits forever.
            (Unit 5.4.2 covers `asyncio.timeout`, the context-manager form.)
            """
        ),
        code(
            """
            async def slow_quote() -> int:
                try:
                    await asyncio.sleep(1)
                    return 100
                except asyncio.CancelledError:
                    print("  slow_quote: cancelled by wait_for")
                    raise  # always re-raise CancelledError


            try:
                await asyncio.wait_for(slow_quote(), timeout=0.05)
            except TimeoutError as error:
                print(f"{type(error).__name__} after 0.05 s")
            print(f"{await asyncio.wait_for(fetch_menu('tea', 0.01), timeout=1)=}")
            print(f"{await asyncio.wait_for(fetch_menu('snacks', 0.01), timeout=None)=}")
            """
        ),
        md(
            """
            **Top-level `await` in Jupyter.** ipykernel runs its message handling as
            tasks on its own asyncio loop. A cell *without* `await` runs synchronously
            inside the kernel's `shell_main` task (that is why
            `asyncio.get_running_loop()` worked in the setup cell). A cell *with* a
            top-level `await` is compiled as a coroutine (`%autoawait` is on by default)
            and awaited by that task, so it can `await` directly, and tasks created in one
            cell keep running after the cell finishes. In a `.py` script none of that
            exists: write `async def main()` and call `asyncio.run(main())`.
            """
        ),
        code(
            """
            await asyncio.sleep(0)  # a top-level await: IPython runs this cell as a coroutine
            cell_frames = [entry.frame.f_code.co_name for entry in asyncio.capture_call_graph().call_stack]
            print(f"running loop: {type(asyncio.get_running_loop()).__name__}")
            print(f"this cell runs inside a task: {asyncio.current_task() is not None}")
            print(f"innermost frames of this cell's task: {cell_frames[:3]}")
            print(
                f"tasks alive on the kernel loop: {len(asyncio.all_tasks())} (ipykernel's own tasks included)"
            )
            """
        ),
    ]


JS_ORDER_SOURCE = """
const fs = require("node:fs");

async function work() {
  console.log("work() body");
  await null;
  console.log("work() after await");
}

console.log("script start");
setTimeout(() => {
  console.log("setTimeout 0");
  fs.readFile(__filename, () => {
    console.log("readFile callback");
    setTimeout(() => console.log("setTimeout 0 from I/O"), 0);
    setImmediate(() => console.log("setImmediate from I/O"));
  });
}, 0);
Promise.resolve().then(() => console.log("promise.then"));
process.nextTick(() => console.log("nextTick"));
work();
console.log("script end");
"""

JS_ORDER_OUTPUT = """
script start
work() body
script end
nextTick
promise.then
work() after await
setTimeout 0
readFile callback
setImmediate from I/O
setTimeout 0 from I/O
"""


def _indented(text: str, spaces: int) -> str:
    """Indent every line after the first (to embed a block inside an md() string)."""
    lines = text.strip("\n").splitlines()
    return ("\n" + " " * spaces).join(lines)


def _js_bridge_cells_part_1() -> list[NotebookNode]:
    """5.3.9 JS bridge: event-loop models and the ordering demo."""
    return [
        md(
            """
            ### 5.3.9 JS bridge, in depth

            **Node's event loop** (libuv) goes round a fixed cycle of **phases**, each
            with its own queue:

            | Phase | Runs |
            | --- | --- |
            | timers | expired `setTimeout` / `setInterval` callbacks |
            | pending callbacks | some deferred system callbacks (e.g. TCP errors) |
            | idle, prepare | internal |
            | poll | wait for I/O (epoll/kqueue/IOCP) and run I/O callbacks |
            | check | `setImmediate` callbacks |
            | close callbacks | `'close'` events |

            On top of that, Node has two queues that are **drained completely after every
            single callback** (since Node 11): first the `process.nextTick` queue, then
            the **microtask** queue (`Promise` reactions, `await` continuations,
            `queueMicrotask`). Microtasks always run before the loop moves on.

            **asyncio has no phases and no microtask queue.** One `_run_once` iteration
            selects, appends ready I/O callbacks and due timers to **one FIFO ready
            queue**, and runs the handles that were queued at the start. A Future
            callback, a Task step, a `call_soon` callback and a due timer are all just
            handles in that queue.

            ```mermaid
            flowchart LR
                subgraph Node["Node.js (libuv)"]
                    direction TB
                    T[timers] --> P[pending] --> I[idle / prepare] --> PO[poll: I/O] --> C["check: setImmediate"] --> CL[close] --> T
                    M["after EVERY callback: drain nextTick queue, then microtasks"]
                end
                subgraph Py["asyncio"]
                    direction TB
                    S["select(timeout)"] --> E["append I/O callbacks"] --> D["append due timers"] --> R["run the ntodo handles queued now"] --> S
                end
            ```

            <details><summary>ASCII version of the diagram</summary>

            ```text
            Node.js (libuv)                               asyncio
            +--> timers ----> pending ----> idle/prepare   +--> select(timeout)
            |                                  |           |        |
            |    close <---- check <---- poll (I/O)        |    append ready I/O callbacks
            |      |      (setImmediate)                   |        |
            +------+                                       |    append due timers
            after EVERY callback: drain process.nextTick,  |        |
            then drain ALL microtasks (promises, await)    +--- run the handles queued now (FIFO)
            ```

            </details>

            | Node.js | asyncio |
            | --- | --- |
            | libuv thread pool (`UV_THREADPOOL_SIZE`, default 4) runs `fs`, `dns.lookup`, `crypto.pbkdf2`, `zlib` | the loop's default `ThreadPoolExecutor` (`min(32, cpus + 4)` threads) runs whatever you pass to `asyncio.to_thread` / `run_in_executor`; asyncio has **no async file I/O** at all (aiofiles uses threads) |
            | network sockets use epoll/kqueue directly | the same |
            | `Promise` (always eager, never cancellable) | `Future` (result slot, cancellable) + `Task` (drives a coroutine) |
            | `async function` call starts running at once | coroutine call is lazy; `create_task` schedules it |

            **Eager Promises vs lazy coroutines**, side by side. In JS, `placeOrder()`
            prints immediately and the promise is already running. In Python nothing
            happens until the coroutine is awaited or wrapped in a task:

            ```javascript
            async function placeOrder() { console.log("  placeOrder body runs"); return "order-1"; }
            console.log("calling placeOrder() ...");
            const pending = placeOrder();          // prints "placeOrder body runs" right here
            console.log("... returned a Promise that is already settled");
            ```
            """
        ),
        code(
            """
            async def place_order() -> str:
                print("  place_order body runs")
                return "order-1"


            print("calling place_order() ...")
            pending_order = place_order()
            print("... returned a coroutine; nothing ran")
            order_task = asyncio.create_task(pending_order)
            print(f"create_task scheduled it: done={order_task.done()}")
            print(f"{await order_task=}")
            """
        ),
        md(
            f"""
            #### Side-by-side ordering demo

            The same program in both languages: a script that logs, schedules a 0 ms
            timer (which starts a file read), queues a promise reaction and a
            `nextTick`, calls an async function, and logs again. In Node, a
            `setTimeout(0)` and a `setImmediate` scheduled from the *main script* can run
            in either order, so they are scheduled from inside the I/O callback, where
            the order is guaranteed.

            ```javascript
            {_indented(JS_ORDER_SOURCE, 12)}
            ```

            Known output (Node v24.21.0, the same on every run):

            ```text
            {_indented(JS_ORDER_OUTPUT, 12)}
            ```

            The Python version maps each line to its closest equivalent: `setTimeout(0)`
            → `loop.call_later(0, ...)`, `fs.readFile` → `asyncio.to_thread(read_bytes)`
            (a thread, like libuv's pool), `setImmediate` → `loop.call_soon`,
            `Promise.resolve().then(cb)` → a resolved Future with a done-callback,
            `process.nextTick` → `loop.call_soon` (there is no closer match), calling
            `work()` → `asyncio.create_task(work())`, `await null` →
            `await asyncio.sleep(0)`. It runs as a script so that, like Node, it starts
            on a fresh loop:
            """
        ),
        code(
            '''
            PYTHON_ORDER_SOURCE = """
            import asyncio
            from pathlib import Path


            async def work():
                print("work() body")
                await asyncio.sleep(0)
                print("work() after await")


            def on_file_read(_):
                print("to_thread(read) done callback")
                loop.call_later(0, print, "call_later 0 from I/O")
                loop.call_soon(print, "call_soon from I/O")


            def on_timer():
                print("call_later 0")
                reading = asyncio.ensure_future(asyncio.to_thread(Path(__file__).read_bytes))
                reading.add_done_callback(on_file_read)


            async def main():
                global loop
                loop = asyncio.get_running_loop()
                print("script start")
                loop.call_later(0, on_timer)
                resolved = loop.create_future()
                resolved.add_done_callback(lambda _: print("future done callback"))
                resolved.set_result(None)
                loop.call_soon(print, "call_soon")
                asyncio.create_task(work())
                print("script end")
                await asyncio.sleep(0.2)


            asyncio.run(main())
            """
            python_order_output = run_child(PYTHON_ORDER_SOURCE)
            print(python_order_output)
            '''
        ),
        md(
            """
            Every difference, line by line (the Python output above is also the same on
            every run):

            | # | Node | Python | Why |
            | --- | --- | --- | --- |
            | 2 | `work() body` prints **before** `script end` | `work() body` prints **after** `script end` | JS async functions run synchronously up to the first `await`; `create_task` only schedules the coroutine. (`create_task(..., eager_start=True)` would match Node.) |
            | 3–4 | `nextTick` runs before `promise.then` | the Future callback runs before `call_soon` | Node drains the nextTick queue before the microtask queue. asyncio has one FIFO: `set_result` queued the callback first, then `call_soon` queued its print |
            | 5–6 | `work() after await` runs **before** `setTimeout 0` | `call_later 0` runs **before** `work() after await` | In Node, the `await` continuation is a microtask, and all microtasks finish before the timers phase. In asyncio, the 0 s timer was already due when the iteration started, so it joined the ready queue in that same iteration, right behind the `work()` step. The continuation after `sleep(0)` is queued only when `work()` yields, so it runs one iteration later |
            | 7 | `readFile callback` (poll phase) | `to_thread(read) done callback` | both are I/O completions arriving from a thread pool; asyncio delivers it as a Future callback through the self-pipe and the selector |
            | 8–9 | `setImmediate` beats `setTimeout 0` (check phase comes right after poll) | `call_soon` beats `call_later(0)` | Node: phase order. Python: the `call_soon` handle is already in the ready queue when the timer becomes due and is appended after it |

            If `node` is installed, the next cell runs the JS program and compares it
            with the known output (otherwise it prints a skip message):
            """
        ),
        code(
            f'''
            JS_ORDER_SOURCE = """
            {_indented(JS_ORDER_SOURCE, 12)}
            """
            JS_ORDER_OUTPUT = """
            {_indented(JS_ORDER_OUTPUT, 12)}
            """
            node_path = shutil.which("node")
            if node_path is None:
                print("node not found on PATH: skipping the live JS run (the known output is above)")
            else:
                js_script = PHASE5_DIR / "order_demo.js"
                js_script.write_text(textwrap.dedent(JS_ORDER_SOURCE).lstrip(), encoding="utf-8")
                node_command = [node_path, str(js_script)]
                node_run = subprocess.run(node_command, capture_output=True, text=True, timeout=30)
                version_run = subprocess.run([node_path, "--version"], capture_output=True, text=True)
                node_version = version_run.stdout.strip()
                print(node_run.stdout.rstrip())
                matches = node_run.stdout.strip() == JS_ORDER_OUTPUT.strip()
                print(f"node {{node_version}}: matches the known output: {{matches}}")
            '''
        ),
    ]


def _js_bridge_cells_part_2() -> list[NotebookNode]:
    """5.3.9 JS bridge: microtasks, combinators, timers, thread pool, workers."""
    return [
        md(
            """
            #### Microtasks vs the ready queue

            Because Node drains *all* microtasks before moving to the next phase, a chain
            of microtasks that keeps queueing more starves timers and I/O completely:

            ```javascript
            let spins = 0;
            setTimeout(() => console.log(`setTimeout ran after ${spins} microtasks`), 0);
            function spin() { spins += 1; if (spins < 100000) queueMicrotask(spin); }
            spin();
            // Output (Node v24.21.0): setTimeout ran after 100000 microtasks
            ```

            asyncio runs only the handles that were queued when the iteration started,
            so a self-re-queueing `call_soon` chain is interleaved with timers and I/O:
            the 0 s timer gets its turn after a couple of spins.
            """
        ),
        code(
            '''
            spin_count = 0
            timer_fired = KERNEL_LOOP.create_future()


            def spin() -> None:
                """Re-queue itself with call_soon, like the JS queueMicrotask chain."""
                global spin_count
                spin_count += 1
                if spin_count < 100_000 and not timer_fired.done():
                    KERNEL_LOOP.call_soon(spin)


            KERNEL_LOOP.call_later(0, lambda: timer_fired.set_result(spin_count))
            spin()
            print(f"call_later(0) ran after {await timer_fired} call_soon spins")
            '''
        ),
        md(
            """
            #### Promise combinators and timers

            | JavaScript | asyncio | Note |
            | --- | --- | --- |
            | `Promise.all(ps)` | `await asyncio.gather(*aws)` or a `TaskGroup` | first failure propagates; `gather` does not cancel the others, `TaskGroup` does (5.4.1) |
            | `Promise.allSettled(ps)` | `await asyncio.gather(*aws, return_exceptions=True)` | exceptions come back as values |
            | `Promise.race(ps)` | `asyncio.wait(tasks, return_when=FIRST_COMPLETED)` | you can (and should) cancel the losers; Lab 5.3 exercise 4 builds `race()` |
            | `Promise.any(ps)` | iterate `asyncio.as_completed(aws)` and return the first success | |
            | `setTimeout(fn, ms)` / `clearTimeout(t)` | `handle = loop.call_later(seconds, fn)` / `handle.cancel()` | inside a coroutine, usually just `await asyncio.sleep(seconds)` |
            | `setImmediate(fn)` | `loop.call_soon(fn)` | |
            | `new Promise(resolve => ...)` | `future = loop.create_future()`; later `future.set_result(value)` | |

            `Promise.all` → `gather`: results come back in argument order, whatever the
            completion order. If one fails, `gather` raises that exception, and the others
            keep running:
            """
        ),
        code(
            """
            async def stock_level(sku: str, seconds: float, fail: bool = False) -> int:
                await asyncio.sleep(seconds)
                if fail:
                    raise LookupError(f"no such sku: {sku}")
                return len(sku) * 10


            print(f"{await asyncio.gather(stock_level('chai', 0.03), stock_level('vada', 0.01))=}")
            try:
                await asyncio.gather(stock_level("chai", 0.01), stock_level("unknown", 0.01, fail=True))
            except LookupError as error:
                print(f"gather raised the first failure: {type(error).__name__}: {error}")
            """
        ),
        md(
            """
            `Promise.allSettled` → `gather(..., return_exceptions=True)`. The helper
            reshapes the result into JS's `{status, value | reason}` records:
            """
        ),
        code(
            '''
            def settled(results: list[object]) -> list[dict[str, object]]:
                """Shape gather(return_exceptions=True) results like Promise.allSettled."""
                return [
                    {"status": "rejected", "reason": repr(result)}
                    if isinstance(result, BaseException)
                    else {"status": "fulfilled", "value": result}
                    for result in results
                ]


            settled_results = await asyncio.gather(
                stock_level("chai", 0.01), stock_level("ghost", 0.01, fail=True), return_exceptions=True
            )
            for record in settled(settled_results):
                print(record)
            '''
        ),
        md(
            """
            `Promise.race` → `asyncio.wait(..., return_when=FIRST_COMPLETED)`, which
            returns `(done, pending)` sets of tasks as soon as one finishes. The bite:
            the losers are **still running** unless you cancel them (JS cannot cancel
            them at all). Lab 5.3 exercise 4 turns this into a proper `race()`.
            """
        ),
        code(
            """
            mirror_tasks = [
                asyncio.create_task(stock_level(name, seconds), name=name)
                for name, seconds in (("mirror-slow", 0.2), ("mirror-fast", 0.01), ("mirror-mid", 0.1))
            ]
            done, pending = await asyncio.wait(mirror_tasks, return_when=asyncio.FIRST_COMPLETED)
            winner = done.pop()
            print(f"winner: {winner.get_name()} -> {winner.result()}")
            print(f"still running: {sorted(task.get_name() for task in pending if not task.done())}")
            for task in pending:
                task.cancel()  # clean up the losers
            await asyncio.wait(pending)
            print(f"after cleanup: all losers cancelled = {all(task.cancelled() for task in pending)}")
            """
        ),
        md(
            """
            `setTimeout` → `loop.call_later`; `clearTimeout` → `handle.cancel()`;
            `setInterval` → re-arm from the callback (or, in a coroutine, a loop around
            `await asyncio.sleep(...)`):
            """
        ),
        code(
            '''
            ticks: list[str] = []
            interval_done = KERNEL_LOOP.create_future()
            interval_start = KERNEL_LOOP.time()


            def every_20_ms(remaining: int) -> None:
                """setInterval stand-in: do the work, then schedule the next tick."""
                ticks.append(f"+{(KERNEL_LOOP.time() - interval_start) * 1000:.0f} ms")
                if remaining > 1:
                    KERNEL_LOOP.call_later(0.02, every_20_ms, remaining - 1)
                else:
                    interval_done.set_result(None)


            cancelled_timeout = KERNEL_LOOP.call_later(0.01, ticks.append, "never: cancelled")
            cancelled_timeout.cancel()  # clearTimeout
            KERNEL_LOOP.call_later(0.02, every_20_ms, 3)  # setTimeout
            await interval_done
            print(f"ticks: {ticks}")
            '''
        ),
        md(
            """
            `setImmediate` → `loop.call_soon`: run a callback on the next loop iteration,
            after the code that is running now:
            """
        ),
        code(
            """
            immediate_log: list[str] = []
            KERNEL_LOOP.call_soon(immediate_log.append, "call_soon callback")
            immediate_log.append("current code continues")
            await asyncio.sleep(0)
            print(immediate_log)
            """
        ),
        md(
            """
            #### Promise vs Future/Task

            | | JS `Promise` | asyncio `Future` / `Task` |
            | --- | --- | --- |
            | Start | the executor / async body runs immediately | a Future is passive; a Task starts on the next iteration (unless eager) |
            | Settle twice | silently ignored | `InvalidStateError` (5.3.7) |
            | Cancel | impossible (use `AbortController` by convention) | `task.cancel()` throws `CancelledError` into the coroutine |
            | Continuations | `.then(cb)`: a microtask | `add_done_callback(cb)`: a `call_soon` handle; receives the Future |
            | Unhandled failure | `unhandledRejection` event | "Task exception was never retrieved", logged when the Task is garbage-collected |
            | Await twice | fine, same value | fine, same value |

            `then` vs `add_done_callback`: the callback receives the Future itself, not
            its value, and its return value is ignored (no chaining):
            """
        ),
        code(
            """
            settled_order = KERNEL_LOOP.create_future()
            settled_order.add_done_callback(
                lambda future: print(f"  done-callback got a {type(future).__name__}: {future.result()!r}")
            )
            settled_order.set_result("order-9")
            print(f"{await settled_order=} {await settled_order=}  (awaiting twice is fine)")
            """
        ),
        md(
            """
            #### The libuv thread pool vs asyncio's default executor

            Node runs some blocking work (file system, `dns.lookup`, `crypto.pbkdf2`,
            `zlib`) on a pool of **4** threads by default. Eight `pbkdf2` calls finish in
            two waves:

            ```javascript
            const crypto = require("node:crypto");
            const start = performance.now();
            for (let i = 0; i < 8; i++) {
              crypto.pbkdf2("pw", "salt", 200000, 32, "sha256", () =>
                console.log(`hash ${i} done at ${Math.round(performance.now() - start)} ms`));
            }
            // Typical output (Node v24.21.0, 16 cores): hashes 0-3 at ~28 ms, hashes 4-7 at ~60 ms
            ```

            asyncio never moves work to a thread on its own: you ask for it with
            `asyncio.to_thread(func, ...)` (or `loop.run_in_executor`). The loop's default
            executor is a `ThreadPoolExecutor` with `min(32, os.process_cpu_count() + 4)`
            workers, created on first use. `hashlib.pbkdf2_hmac` releases the GIL, so
            eight of them run in parallel:
            """
        ),
        code(
            '''
            import hashlib


            def stretch_password(index: int) -> int:
                """CPU-heavy C code that releases the GIL, like crypto.pbkdf2."""
                hashlib.pbkdf2_hmac("sha256", b"pw", b"salt", 200_000 * DEMO_SCALE)
                return index


            pool_started = time.perf_counter()
            hash_finish_ms: list[str] = []
            for finished in asyncio.as_completed(
                [asyncio.to_thread(stretch_password, index) for index in range(8)]
            ):
                hash_finish_ms.append(f"{await finished}@{(time.perf_counter() - pool_started) * 1000:.0f}ms")
            print(" ".join(hash_finish_ms))
            executor = KERNEL_LOOP._default_executor
            print(f"default executor: {type(executor).__name__} with {executor._max_workers} workers")
            '''
        ),
        md(
            """
            #### `worker_threads` vs processes and subinterpreters

            | Node | Python | Shared memory | Start-up | Use for |
            | --- | --- | --- | --- | --- |
            | the main event loop | one asyncio loop per thread | — | — | many concurrent I/O waits |
            | libuv thread pool | `asyncio.to_thread` / `ThreadPoolExecutor` | yes (one heap) | ~50 µs | blocking libraries, C code that releases the GIL |
            | `worker_threads` (separate V8 isolate per thread) | subinterpreters (`InterpreterPoolExecutor`, Unit 5.2.6), or processes | no (messages; `SharedArrayBuffer` / `shared_memory`) | ms | CPU-bound Python code |
            | `child_process` / `cluster` | `ProcessPoolExecutor`, `multiprocessing` (Unit 5.2) | no | tens of ms | CPU-bound work, isolation |

            From async code, CPU-bound work goes to a process pool with
            `await loop.run_in_executor(process_pool, func, *args)` (Unit 5.4.6), the
            equivalent of posting a message to a worker and awaiting its reply.
            """
        ),
    ]


def _function_color_cells() -> list[NotebookNode]:
    """5.3.10 Function colors."""
    return [
        md(
            """
            ### 5.3.10 Function colors

            Bob Nystrom's essay *What Color is Your Function?* (2015) names the problem:
            async ("red") functions can only be awaited from other async functions, and
            sync ("blue") functions cannot wait for red ones. JS and Python share it.
            The rules at the boundaries:

            | From | To | How | Cost / risk |
            | --- | --- | --- | --- |
            | async | fast sync code | just call it | none |
            | async | blocking sync code (`time.sleep`, `requests`, heavy CPU) | `await asyncio.to_thread(func)` / `run_in_executor` | a thread (or a process for CPU work); calling it directly freezes the loop |
            | async | async | `await` | none |
            | sync | async, at the program's entry | `asyncio.run(main())` / `asyncio.Runner` | one loop per call; fails if a loop is already running |
            | sync, in another thread | async on a running loop | `asyncio.run_coroutine_threadsafe(coro, loop)` | returns a `concurrent.futures.Future` to block on (5.4.11) |
            | sync | async, called by mistake | — | you get a coroutine object, not a result, plus a "never awaited" warning |

            Colors also **spread upwards**: once a low-level function needs to `await`
            (say, a database call), every caller must become `async` too, up to the
            entry point. Decide early which layers are async.

            The classic mistake: a sync function calls an async one and gets a coroutine
            object instead of a number:
            """
        ),
        code(
            '''
            async def get_stock(sku: str) -> int:
                await asyncio.sleep(0)
                return 12


            def stock_line(sku: str) -> str:
                """BUG: a sync function cannot await, so it formats a coroutine object."""
                stock = get_stock(sku)
                return f"{sku}: {stock}"


            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                print(re.sub(r" at 0x[0-9a-f]+", "", stock_line("chai")))
                gc.collect()
            print([f"{caught.category.__name__}: {caught.message}" for caught in caught_warnings])
            '''
        ),
        md(
            """
            **Sync code calling into a running loop.** Legacy sync code running in a
            worker thread can submit a coroutine to the loop with
            `run_coroutine_threadsafe` and block on the returned
            `concurrent.futures.Future`. (The kernel's loop is not blocked: the sync code
            runs in a thread via `to_thread`.)
            """
        ),
        code(
            '''
            def legacy_stock_report(loop: asyncio.AbstractEventLoop) -> str:
                """Sync code in a worker thread asking the event loop for a value."""
                stock_future = asyncio.run_coroutine_threadsafe(get_stock("chai"), loop)
                return f"chai: {stock_future.result(timeout=1)} (computed on the loop thread)"


            print(await asyncio.to_thread(legacy_stock_report, KERNEL_LOOP))
            '''
        ),
        md(
            """
            **Async code calling blocking sync code.** Calling it directly stalls every
            other task; `to_thread` keeps the loop free. Three 0.1 s blocking calls:
            """
        ),
        code(
            '''
            def legacy_price_lookup(sku: str) -> int:
                """A blocking library call (think requests.get)."""
                time.sleep(0.1)
                return len(sku)


            async def price_directly(sku: str) -> int:
                return legacy_price_lookup(sku)  # blocks the loop


            async def price_in_thread(sku: str) -> int:
                return await asyncio.to_thread(legacy_price_lookup, sku)


            with Timer("blocking calls made directly in async code") as direct_timer:
                await asyncio.gather(*(price_directly(sku) for sku in ("chai", "vada", "idli")))
            with Timer("the same calls via asyncio.to_thread") as thread_timer:
                await asyncio.gather(*(price_in_thread(sku) for sku in ("chai", "vada", "idli")))
            print(f"ratio: {direct_timer.elapsed_seconds / thread_timer.elapsed_seconds:.1f}x")
            '''
        ),
    ]


def _predict_cells() -> list[NotebookNode]:
    """Predict-the-output questions for Unit 5.3."""
    return [
        md("#### Predict the output"),
        *predict_cells(
            """
            async def say(word):
                print(word)

            async def main():
                asyncio.create_task(say("A"))
                print("B")
                await asyncio.sleep(0)
                print("C")

            await main()
            """,
            """
            `B`, `A`, `C`. `create_task` only puts the new task's first step on the
            ready queue. `main` keeps running and prints `B`; at `sleep(0)` it yields,
            the loop runs the queued task (`A`), then `main` resumes (`C`). In JS,
            calling `say("A")` would print `A` first.
            """,
            """
            async def say(word: str) -> None:
                print(word)


            async def main() -> None:
                asyncio.create_task(say("A"))
                print("B")
                await asyncio.sleep(0)
                print("C")


            await main()
            """,
        ),
        *predict_cells(
            """
            finished = []

            async def step(name, seconds):
                await asyncio.sleep(seconds)
                finished.append(name)
                return name

            results = await asyncio.gather(step("slow", 0.02), step("fast", 0.01))
            print(finished, results)
            """,
            """
            `['fast', 'slow'] ['slow', 'fast']`. The tasks *finish* in time order, so
            `finished` is fast-first, but `gather` returns results in *argument* order,
            exactly like `Promise.all`.
            """,
            """
            finished_steps: list[str] = []


            async def step(name: str, seconds: float) -> str:
                await asyncio.sleep(seconds)
                finished_steps.append(name)
                return name


            step_results = await asyncio.gather(step("slow", 0.02), step("fast", 0.01))
            print(finished_steps, step_results)
            """,
        ),
        *predict_cells(
            """
            async def compute():
                return 42

            coro = compute()
            print(type(coro).__name__, inspect.getcoroutinestate(coro))
            print(await coro)
            coro.send(None)
            """,
            """
            `coroutine CORO_CREATED`, then `42`, then
            `RuntimeError: cannot reuse already awaited coroutine`. A coroutine object
            is single-use, like a generator: once it has run to completion it cannot be
            restarted. (A JS Promise, by contrast, can be awaited any number of times;
            in Python, wrap the coroutine in a Task if several places need its result.)
            """,
            """
            async def compute() -> int:
                return 42


            single_use = compute()
            print(type(single_use).__name__, inspect.getcoroutinestate(single_use))
            print(await single_use)
            print(raised_message(lambda: single_use.send(None)))
            """,
        ),
    ]


PUZZLE_SOURCES = [
    """
    async def puzzle_1(log: list[str]) -> None:
        async def child() -> None:
            log.append("child")

        asyncio.create_task(child())
        log.append("parent")
        await asyncio.sleep(0)
    """,
    """
    async def puzzle_2(log: list[str]) -> None:
        async def child(name: str) -> None:
            log.append(name)

        background = asyncio.create_task(child("task"))
        await child("direct")
        log.append("after direct")
        await background
    """,
    """
    async def puzzle_3(log: list[str]) -> None:
        loop = asyncio.get_running_loop()
        loop.call_later(0, log.append, "later")
        loop.call_soon(log.append, "soon")
        log.append("now")
        await asyncio.sleep(0.01)
    """,
    """
    async def puzzle_4(log: list[str]) -> None:  # needs Python 3.14+ (eager_start)
        async def child(name: str) -> None:
            log.append(f"{name} start")
            await asyncio.sleep(0)
            log.append(f"{name} end")

        asyncio.create_task(child("lazy"))
        asyncio.create_task(child("eager"), eager_start=True)
        log.append("parent")
        await asyncio.sleep(0.01)
    """,
    """
    async def puzzle_5(log: list[str]) -> None:
        async def child() -> int:
            log.append("child")
            return 1

        task = asyncio.create_task(child())
        task.add_done_callback(lambda _: log.append("callback"))
        await task
        log.append("awaiter")
    """,
    """
    async def puzzle_6(log: list[str]) -> None:
        async def step(name: str, delay: float) -> str:
            await asyncio.sleep(delay)
            log.append(name)
            return name

        results = await asyncio.gather(step("a", 0.02), step("b", 0), step("c", 0.01))
        log.append("+".join(results))
    """,
    """
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
    """,
    """
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
    """,
]


def _puzzle_markdown() -> str:
    """The eight puzzles as one markdown block."""
    import textwrap

    blocks = []
    for number, source in enumerate(PUZZLE_SOURCES, start=1):
        blocks.append(f"**Puzzle {number}**\n\n```python\n{textwrap.dedent(source).strip()}\n```")
    return "\n\n".join(blocks)


def _puzzle_code() -> str:
    """The eight puzzles as runnable code plus the PUZZLES table."""
    import textwrap

    functions = "\n\n\n".join(textwrap.dedent(source).strip() for source in PUZZLE_SOURCES)
    table = "".join(
        f"    {number}: puzzle_{number},\n" for number in range(1, len(PUZZLE_SOURCES) + 1)
    )
    return f'{functions}\n\n\nPUZZLES = {{\n{table}}}\nprint(f"{{len(PUZZLES)}} puzzles loaded")'


LAB_SETUP_SOURCE = r'''
import contextlib
import functools
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


print("Lab 5.3 helpers ready: outcome, quiet_unawaited, run_toy, run_puzzle")
'''


def _lab_cells_part_1() -> list[NotebookNode]:
    """Lab 5.3 exercises 1-3."""
    return [
        md(
            """
            ### Lab 5.3

            Six exercises. Replace each `raise NotImplementedError`, then run the check
            cell. Until you finish, the checks print FAIL; that is expected. Exercise 2
            uses `ToyLoop` from 5.3.3 and exercise 1 uses `Ask` from 5.3.4: run those
            sections first.
            """
        ),
        code(LAB_SETUP_SOURCE),
        md(
            """
            #### Exercise 1 — drive a coroutine by hand

            Write `drive(coroutine, responder)`. Start the coroutine with `send(None)`.
            Every value it yields is a *request*: record it and answer it with
            `send(responder(request))`. If `responder` raises an `Exception`, deliver that
            exception into the coroutine with `throw(error)` instead. When the coroutine
            returns, return `(list of requests, return value)`. An exception the
            coroutine does not handle must propagate out of `drive`.

            The test coroutines below use `Ask` from 5.3.4.
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            def drive(
                coroutine: Coroutine[Any, Any, Any], responder: Callable[[object], object]
            ) -> tuple[list[object], object]:
                """Run coroutine to completion, answering each yielded request with responder."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 1:"),
        code(
            """
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
                        ("no requests at all", lambda: drive(no_questions(), book_responder), ([], "instant")),
                    ]
                )
            """
        ),
        md(
            """
            #### Exercise 2 — add `gather` to the toy loop

            Write `toy_gather(loop, coroutines)`, a *generator* for the toy loop: it
            spawns every toy coroutine on `loop`, waits for all of them with
            `("join", task)`, and returns their results **in input order** (not finishing
            order). Callers use it with `results = yield from toy_gather(loop, [...])`.
            The waits must overlap: three sleeps of 0.2, 0.1 and 0.15 s take about 0.2 s.
            """
        ),
        code(
            '''
            def toy_sleep_then(value: object, seconds: float) -> ToyCoroutine:
                """Sleep on the toy loop, then return value."""
                yield ("sleep", seconds)
                return value


            def toy_instant(value: object) -> ToyCoroutine:
                """Return value on the first step, without ever yielding."""
                if False:
                    yield
                return value
            '''
        ),
        md("Your solution:"),
        code(
            '''
            def toy_gather(
                loop: ToyLoop, coroutines: list[ToyCoroutine]
            ) -> Generator[object, object, list[object]]:
                """Spawn every coroutine on loop, join them all, return results in input order."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 2:"),
        code(
            """
            def gather_three(loop: ToyLoop) -> ToyCoroutine:
                specs = [("a", 0.2), ("b", 0.1), ("c", 0.15)]
                return (
                    yield from toy_gather(loop, [toy_sleep_then(value, seconds) for value, seconds in specs])
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
            """
        ),
        md(
            """
            #### Exercise 3 — turn 5 s of sequential sleeps into 1 s of concurrent ones

            `load_dashboard_sequential()` fetches five widgets one after another, each
            taking 1 s. Write `load_dashboard_concurrent()` that returns the same dict
            (same keys, same order) in about 1 s. The next cell times the sequential
            version once (about 5 s).
            """
        ),
        code(
            """
            WIDGETS = ["sales", "stock", "orders", "returns", "reviews"]


            async def fetch_widget(name: str, seconds: float = 1.0) -> str:
                await asyncio.sleep(seconds)
                return f"{name}: ok"


            async def load_dashboard_sequential() -> dict[str, str]:
                return {name: await fetch_widget(name) for name in WIDGETS}


            with Timer("load_dashboard_sequential"):
                print(await load_dashboard_sequential())
            """
        ),
        md("Your solution:"),
        code(
            '''
            async def load_dashboard_concurrent() -> dict[str, str]:
                """The same dict as load_dashboard_sequential(), in about 1 s."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 3:"),
        code(
            """
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
                    ("about 1 s (< 1.5 s)", lambda: finished and dashboard_timer.elapsed_seconds < 1.5, True),
                ]
            )
            """
        ),
    ]


def _lab_cells_part_2() -> list[NotebookNode]:
    """Lab 5.3 exercises 4-6."""
    return [
        md(
            """
            #### Exercise 4 — `race(coroutines)`

            Write `race(coroutines)`, a better `Promise.race`: run all the coroutines
            concurrently, and as soon as the first one finishes, **cancel the others and
            wait until they have finished cancelling**, then return the winner's result
            (or raise the winner's exception). An empty input raises `ValueError`.
            `contender` records its cancellation in `RACE_LOG`.
            """
        ),
        code(
            """
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
            """
        ),
        md("Your solution:"),
        code(
            '''
            async def race(coroutines: Iterable[Coroutine[Any, Any, Any]]) -> Any:
                """Return the first result (or raise the first error); cancel and await the rest."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 4:"),
        code(
            """
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
                    ("losers cancelled after a failure too", lambda: failure_cancelled, ["steady cancelled"]),
                    ("one contender", lambda: race_single, "solo"),
                    ("no contenders -> ValueError", lambda: race_empty, "raised ValueError"),
                ]
            )
            """
        ),
        md(
            f"""
            #### Exercise 5 — eight event-loop ordering puzzles

            Each puzzle appends strings to `log`. For each one, predict the final `log`
            **before running anything**, using the rules from 5.3.5–5.3.9 (one FIFO
            ready queue; `create_task` schedules; awaiting a coroutine that does not
            suspend never yields; due timers join the queue after the handles already in
            it; done-callbacks run in registration order). Then write your answers in
            `predictions()`. The runner awaits the puzzle, then gives stragglers 50 ms.

            {_indented(_puzzle_markdown(), 12)}
            """
        ),
        code(_puzzle_code()),
        md("Your predictions:"),
        code(
            '''
            def predictions() -> dict[int, list[str]]:
                """Your predicted final log for each puzzle: {1: [...], 2: [...], ..., 8: [...]}."""
                raise NotImplementedError
            '''
        ),
        md("Check exercise 5 (it runs each puzzle and compares the log with your prediction):"),
        code(
            """
            puzzle_logs = {}
            for number, puzzle in PUZZLES.items():
                puzzle_logs[number] = await run_puzzle(puzzle)
            run_checks(
                [
                    (f"puzzle {number}", lambda number=number: predictions()[number], log)
                    for number, log in puzzle_logs.items()
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 6 — an asyncio chat server with streams

            Implement `ChatRoom.handle(reader, writer)`, the per-client callback for
            `asyncio.start_server`. Protocol (UTF-8, one message per line):

            - the first line a client sends is its nickname; every **other** member then
              receives `* {nick} joined`;
            - each later line is sent to every other member as `{nick}: {text}`;
            - when the client disconnects (`readline()` returns `b""`), the others
              receive `* {nick} left`.

            Use `writer.write(...)` followed by `await writer.drain()` (backpressure, as
            in 5.3.2). A member that has gone away must not crash the others: catch
            `ConnectionError` while sending. `chat_scenario` starts the server on a free
            port, connects asha, ben and chen, has them talk, and collects what each one
            received.
            """
        ),
        code(
            '''
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
                    clients[nick][1].write(f"{line}\\n".encode())
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
                        lines.append(line.decode().rstrip("\\n"))

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
            '''
        ),
        md("Your solution:"),
        code(
            '''
            class ChatRoom:
                """A chat room served with asyncio streams (protocol in the exercise text)."""

                def __init__(self) -> None:
                    self.members: dict[asyncio.StreamWriter, str] = {}

                async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                    """Serve one client: nickname line first, then chat lines until EOF."""
                    raise NotImplementedError
            '''
        ),
        md("Check exercise 6:"),
        code(
            """
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
                    ("chen's screen", lambda: chat_transcripts.get("chen"), ["asha: hello", "ben: hi asha"]),
                    (
                        "no handler errors",
                        lambda: chat_result["errors"] if isinstance(chat_result, dict) else chat_result,
                        [],
                    ),
                ]
            )
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 5.3."""
    return [
        md(
            """
            ### Recap — Unit 5.3

            | Concept | One-line takeaway | JS / Node equivalent |
            | --- | --- | --- |
            | Why async | One thread, many waiting connections: tasks cost kilobytes, threads cost a stack each | the reason Node exists |
            | OS foundations | Non-blocking sockets + a readiness API (`epoll`, `kqueue`) or completion API (IOCP); `selectors` wraps them | libuv |
            | Toy event loop | Generators + ready queue + timer heap + selector = an event loop | — |
            | Native coroutines | `async def` returns a lazy coroutine; `send`/`throw`/`close` drive it | async functions run eagerly |
            | Awaitables | coroutines, Futures, Tasks, objects with `__await__` | thenables |
            | What `await` does | yields a pending Future up to the Task, which resumes via a done-callback | microtask continuation |
            | The asyncio loop | `_ready` deque + `_scheduled` heap + `_selector`; `_run_once` runs the handles queued at its start | phases + microtask queues |
            | Futures and Tasks | Future = result slot; Task = Future driving a coroutine; keep references; eager tasks skip the loop | `Promise` |
            | Core API | `asyncio.run` / `Runner` at the entry point; `gather` for concurrency; `sleep(0)` to yield; `wait_for` for timeouts | `Promise.all`, `setTimeout` |
            | Ordering | One FIFO; `await` of a non-suspending coroutine does not yield | nextTick → microtasks → phases |
            | Function colors | Async spreads upward; cross with `asyncio.run`, `to_thread`, `run_coroutine_threadsafe` | the same problem |

            **Further reading**

            - [`asyncio`](https://docs.python.org/3/library/asyncio.html):
              [event loop](https://docs.python.org/3/library/asyncio-eventloop.html),
              [coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html),
              [futures](https://docs.python.org/3/library/asyncio-future.html),
              [runners](https://docs.python.org/3/library/asyncio-runner.html),
              [call graph introspection](https://docs.python.org/3/library/asyncio-graph.html) (3.14)
            - [`selectors`](https://docs.python.org/3/library/selectors.html),
              [`select`](https://docs.python.org/3/library/select.html)
            - [PEP 342](https://peps.python.org/pep-0342/) (coroutines via enhanced generators),
              [PEP 380](https://peps.python.org/pep-0380/) (`yield from`),
              [PEP 3156](https://peps.python.org/pep-3156/) (asyncio),
              [PEP 492](https://peps.python.org/pep-0492/) (`async`/`await`)
            - Node.js: [The Node.js event loop](https://nodejs.org/en/learn/asynchronous-work/event-loop-timers-and-nexttick);
              Dan Kegel, *The C10K problem*; Bob Nystrom, *What Color is Your Function?*
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 5.3 and Lab 5.3."""
    return [
        *_overview_cells(),
        *_why_async_cells(),
        *_os_foundation_cells(),
        *_toy_loop_cells_part_1(),
        *_toy_loop_cells_part_2(),
        *_native_coroutine_cells(),
        *_await_cells(),
        *_asyncio_loop_cells(),
        *_future_task_cells(),
        *_core_api_cells(),
        *_js_bridge_cells_part_1(),
        *_js_bridge_cells_part_2(),
        *_function_color_cells(),
        *_predict_cells(),
        *_lab_cells_part_1(),
        *_lab_cells_part_2(),
        *_recap_cells(),
    ]
