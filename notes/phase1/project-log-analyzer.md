# Phase 1 Project — Log Analyzer

[← Previous](unit-1-14-exceptions-and-context-managers.md) · [Index](README.md) · [Next →](cheatsheet.md)

This chapter is a case study. It builds one small but complete tool, an analyzer for a
web server's access log, using nothing beyond what Phase 1 covered. Every stage is a
plain function you can test on its own, and the stages snap together into a lazy
pipeline that streams twenty thousand lines in a single pass. The chapter ends with
thirty predict-the-output questions that revisit every unit of the phase.

## What you will learn

- How to turn a vague requirement ("tell me what is happening on this server") into a
  pipeline of small, testable stages.
- Why generators are the natural shape for log processing, and how to prove a
  pipeline is lazy with `tracemalloc`.
- How to separate *shape* checks (a regular expression) from *rule* checks (a `match`
  statement with guards).
- How to keep going past bad input by collecting exceptions instead of crashing, and
  how to report them all at once with an `ExceptionGroup`.
- How decorators (`@timer`, `@retry`) and context managers (`Timer`) add timing and
  resilience without touching the business logic.

## JavaScript → Python bridge

| In Node.js you might use | Here we use | Why it differs |
| --- | --- | --- |
| `readline` + `for await` | generator + `with open` | Synchronous and lazy, no event loop |
| A regex with named groups | `re.fullmatch` + `(?P<name>…)` | `fullmatch` anchors both ends |
| `switch` + `if` checks | `match` with guards | Destructures and checks in one place |
| `Map` counters | `Counter`, `defaultdict` | Missing keys read as 0 / `[]` |
| `AggregateError` | `ExceptionGroup` + `except*` | Handlers select by type inside the group |
| A retry wrapper (`p-retry`) | `@retry` decorator | Applied once, at definition time |

## The problem

You are handed a web server's access log and asked three questions. What status codes
is the server returning, and in what proportions? Which endpoints are busiest, and how
slow are they for the unlucky few? And how much of the log is garbage? Real logs are
messy: a writer that crashes mid-line leaves a truncated record, an upstream proxy
sometimes writes an HTML error page instead of a log line, and buggy clients send
invented HTTP methods. The tool must survive all of that, count what it rejected, and
still produce an accurate report.

Each well-formed line has six fields:

```text
2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1" 200 23ms
timestamp            client IP  method path          protocol status latency
```

The requirements, one per build step:

1. Generate a seeded synthetic log (so every run is reproducible), with about 2% of
   the lines deliberately broken.
2. Read the log lazily, one line at a time.
3. Parse each line with `re` and `match`.
4. Collect malformed lines without stopping.
5. Aggregate status codes, the top endpoints and the p95 latency.
6. Render an aligned plain-text report.
7. Time the whole run with a context manager.
8. Upload the report through a flaky connection with `@retry`; offer a strict mode
   that fails with every problem at once.
9. Check the whole thing with `run_checks`.

## Design

The tool is a chain of stages. Data flows left to right, one record at a time; the
only branch is where a line fails to parse and is diverted into a list of errors that
the report also reads.

```text
write_synthetic_log
        |
        v
   read_lines        (generator: one (line_number, line) at a time)
        |
        v
  parse_records  ---- MalformedLineError ---->  malformed list
        |                                            |
   AccessRecord                                      |
        v                                            |
    aggregate        (@timer, one pass)              |
        |                                            |
        v                                            |
  render_report  <-----------------------------------+
        |
        v
  upload_report      (@retry on ConnectionError / TimeoutError)
```

Which Phase 1 tools are used where, and why:

| Step | Tools | Why this tool |
| --- | --- | --- |
| 1 Generate | `random.Random(seed)`, f-strings, `with open` | A private RNG keeps runs reproducible |
| 2 Read | generator function, `enumerate` | Constant memory for any file size |
| 3 Parse | `re.fullmatch`, `match` + guards, `NamedTuple` | Shape check, then rule check |
| 4 Collect | custom exception, `try`/`except`/`else` | Catch only the expected failure |
| 5 Aggregate | `Counter`, `defaultdict`, `sorted` key, `re.sub` | One pass, no manual bookkeeping |
| 6 Render | format specs (`<`, `>`, `,`, `.1%`) | Alignment without a library |
| 7 Time | `Timer` context manager, `@timer` | Timing stays out of the logic |
| 8 Upload | `@retry`, `ExceptionGroup`, `except*` | Resilience and all-at-once errors |
| 9 Check | `run_checks` | Tie the output back to the input |

Where each tool is explained:

| Tool | Unit |
| --- | --- |
| Seeded `random`, `//` division | [Unit 1.3](unit-1-3-numeric-and-boolean-data-types.md) |
| f-strings, format specs, `re` | [Unit 1.4](unit-1-4-text-and-binary-data-types.md) |
| `NamedTuple`, `sorted` with a key | [Unit 1.5](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md) |
| `Counter`, `defaultdict`, `frozenset` | [Unit 1.6](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md) |
| `match` with guards | [Unit 1.8](unit-1-8-operators-expressions-and-control-flow.md) |
| `enumerate`, generator expressions | [Unit 1.9](unit-1-9-iteration-comprehensions-and-built-in-functions.md) |
| Keyword-only parameters, `lambda` | [Unit 1.10](unit-1-10-functions-definition-and-arguments.md) |
| `@timer`, `@retry`, `functools.wraps` | [Unit 1.12](unit-1-12-decorators-functools-and-the-call-stack.md) |
| Generator functions, `inspect` states | [Unit 1.13](unit-1-13-iterators-generators-and-itertools.md) |
| Custom exceptions, groups, `with` | [Unit 1.14](unit-1-14-exceptions-and-context-managers.md) |

Two design decisions run through the whole build. First, **every stage takes an
iterable and returns an iterable (or a summary)**, so stages can be tested with a
five-element list and then run on a twenty-thousand-line file without changes.
Second, **side effects live at the edges**: only Step 1 and Step 8 touch the file
system, and the report is a pure function of the summary, which makes Step 9's tests
trivial to write.

## Setup and reused helpers

The project starts with its imports and two small helpers. `raised_error_name` turns
"this call raises" into a value that a test can compare, and `find_repo_root` locates
the repository so the scratch files land in `notebooks/_scratch` no matter where the
code runs from. `run_checks` is the shared test helper used by every lab in the
course: it runs `(label, thunk, expected)` cases and prints PASS or FAIL for each,
never raising.

```python
import datetime as dt
import functools
import hashlib
import inspect
import itertools
import math
import random
import re
import sys
import time
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases; print PASS/FAIL. Never raises."""
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
    """Call thunk; return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: cwd) to the folder with pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working dir")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.version_info[:2]=}")
```

```text
sys.version_info[:2]=(3, 15)
```

Three more helpers are copied unchanged from earlier units, so the project does not
depend on code far away:

| Helper | From | Used for |
| --- | --- | --- |
| `timer(unit=, report=)` | 1.12.3 | Timing `aggregate` |
| `retry(times, exceptions=, …)` | 1.12.6 | The flaky upload |
| `Timer(label, report=)` | 1.14.9 | Timing the whole run |

`timer` is a decorator that works both bare (`@timer`) and with arguments
(`@timer(unit="s")`): the positional-only `func` parameter is filled only in the bare
form. The `try`/`finally` in the wrapper means the time is reported even when the
wrapped function raises. The `report` parameter defaults to `print` but accepts any
callable, which is how the project sends timing lines into a list instead of the
screen.

```python
TIME_UNITS = {"s": 1.0, "ms": 1_000.0, "us": 1_000_000.0}


def timer(
    func: Callable[..., Any] | None = None,
    /,
    *,
    unit: str = "ms",
    report: Callable[[str], object] = print,
) -> Callable[..., Any]:
    """Report how long each call takes. Use as @timer or @timer(unit="s")."""
    if unit not in TIME_UNITS:
        raise ValueError(
            f"unit must be one of {sorted(TIME_UNITS)}, got {unit!r}"
        )

    def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return target(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - started) * TIME_UNITS[unit]
                report(f"{target.__qualname__} took {elapsed:.3f} {unit}")

        return wrapper

    return decorator if func is None else decorator(func)
```

`retry` is a decorator factory: `retry(...)` returns the decorator. It retries only on
the exception types it is given, sleeps `first_delay * backoff ** n` between attempts
(exponential backoff), and re-raises the last error with a bare `raise` once the
attempts run out, so the caller sees the original traceback. The `sleep` parameter is
injectable, so tests can record delays instead of actually waiting.

```python
def retry(
    times: int = 3,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    first_delay: float = 0.1,
    backoff: float = 2.0,
    sleep: Callable[[float], object] = time.sleep,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry on the listed exceptions with exponential backoff."""
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleep(first_delay * backoff ** (attempt - 1))
            raise AssertionError("unreachable")

        return wrapper

    return decorator
```

`Timer` is a class-based context manager: `__enter__` starts the clock, `__exit__`
stops it and reports. Because `__exit__` returns `None` (falsy), any exception raised
inside the `with` block still propagates after the time is reported.

```python
class Timer:
    """Time a with block and report "<label> took <ms> ms"."""

    def __init__(
        self, label: str, report: Callable[[str], object] = print
    ) -> None:
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_seconds = time.perf_counter() - self._started
        self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")
```

> **Note:** `-> Timer` inside the class body works without quotes because annotations
> are evaluated lazily since Python 3.14 (PEP 649). On 3.13 and older you would write
> `-> "Timer"` or add `from __future__ import annotations`.

## Step 1 — Generate a seeded synthetic access log

A log analyzer needs a log, and a test needs a log whose contents are known. The
generator below produces one. It uses its **own** `random.Random(seed)` instance
rather than the module-level functions of `random`: the same seed always gives the
same file, and nothing else in the program shifts the sequence by drawing numbers
from the shared global generator. This is the Python equivalent of passing a seeded
PRNG object around in JavaScript, where `Math.random()` cannot be seeded at all.

Endpoints and status codes are drawn with weights (`rng.choices`), so the traffic
looks realistic: product listings are busy, address changes are rare. Latency is drawn
from a log-normal distribution around a typical value per endpoint. Real latencies
have a long tail (most requests are fast, a few are very slow), and a log-normal
reproduces that shape; `5xx` responses are made five times slower, as timeouts tend
to be.

```python
ENDPOINTS = [  # (method, path template, weight, typical latency in ms)
    ("GET", "/api/products", 30, 40),
    ("GET", "/api/products/{id}", 25, 25),
    ("POST", "/api/cart/items", 12, 60),
    ("GET", "/api/orders/{id}", 10, 80),
    ("GET", "/health", 10, 2),
    ("POST", "/api/checkout", 6, 250),
    ("DELETE", "/api/cart/items/{id}", 4, 30),
    ("PUT", "/api/users/{id}/address", 3, 90),
]
STATUS_WEIGHTS = {
    200: 800,
    201: 50,
    204: 20,
    304: 30,
    400: 30,
    401: 10,
    404: 30,
    429: 10,
    500: 10,
    502: 5,
    503: 5,
}
MALFORMED_KINDS = (
    "truncated",
    "garbage",
    "unknown method",
    "status out of range",
)
GARBAGE_LINES = (
    "-",
    "<html>502 Bad Gateway</html>",
    "Connection reset by peer",
    "GET /",
)


def well_formed_line(rng: random.Random, timestamp: dt.datetime) -> str:
    """One valid access-log line drawn from the weighted tables."""
    endpoint_weights = [endpoint[2] for endpoint in ENDPOINTS]
    method, template, _, typical_ms = rng.choices(
        ENDPOINTS, weights=endpoint_weights
    )[0]
    path = template.replace("{id}", str(rng.randint(1, 5_000)))
    if template == "/api/products" and rng.random() < 0.3:
        path += f"?page={rng.randint(2, 9)}"
    status = rng.choices(
        list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values())
    )[0]
    typical_log = math.log(typical_ms)
    latency_ms = max(1, round(rng.lognormvariate(typical_log, 0.6)))
    if status >= 500:
        latency_ms *= 5
    client_ip = f"10.0.{rng.randint(0, 3)}.{rng.randint(1, 254)}"
    stamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f'{stamp} {client_ip} "{method} {path} HTTP/1.1"'
        f" {status} {latency_ms}ms"
    )
```

`break_line` produces four kinds of damage: a line cut short (a crashed writer), a
garbage line (an upstream error page), an unknown HTTP method, and an impossible
status code. The last two are the interesting ones, because they still *look* like
log lines: a regular expression accepts them, and only the rule check in Step 3 can
reject them. `write_synthetic_log` returns a `Counter` of what it injected, so the
analysis can later be checked against the truth.

```python
def break_line(rng: random.Random, line: str, kind: str) -> str:
    """Damage a valid line in the given way."""
    match kind:
        case "truncated":
            return line[: rng.randint(10, len(line) - 6)]
        case "garbage":
            return rng.choice(GARBAGE_LINES)
        case "unknown method":
            new_method = rng.choice(["FETCH", "BREW"])
            return re.sub(r'"[A-Z]+ ', f'"{new_method} ', line, count=1)
        case "status out of range":
            new_status = rng.choice(["000", "999"])
            return re.sub(r'" \d{3} ', f'" {new_status} ', line, count=1)
        case _:
            raise ValueError(f"unknown kind: {kind!r}")


def write_synthetic_log(
    path: Path, line_count: int, *, seed: int = 42, malformed_rate: float = 0.02
) -> Counter[str]:
    """Write line_count lines; return a Counter of injected damage kinds."""
    rng = random.Random(seed)
    timestamp = dt.datetime(2026, 11, 6, 9, 0, 0)
    injected: Counter[str] = Counter()
    with path.open("w", encoding="utf-8") as log_file:
        for _ in range(line_count):
            timestamp += dt.timedelta(milliseconds=rng.randint(100, 1_500))
            line = well_formed_line(rng, timestamp)
            if rng.random() < malformed_rate:
                kind = rng.choice(MALFORMED_KINDS)
                injected[kind] += 1
                line = break_line(rng, line, kind)
            log_file.write(line + "\n")
    return injected
```

Now write twenty thousand lines to the scratch folder and look at the result. Because
the generator is seeded, these exact lines appear on every run, on every machine.
`itertools.islice` takes the first four lines of the open file without reading the
rest.

```python
LOG_LINE_COUNT = 20_000
log_path = scratch_dir / "phase1_access.log"
injected_kinds = write_synthetic_log(log_path, LOG_LINE_COUNT, seed=42)

injected_total = sum(injected_kinds.values())
print(f"{injected_total} malformed lines injected:")
for kind, kind_count in sorted(injected_kinds.items()):
    print(f"  {kind:<20} {kind_count}")
print(f"file size: {log_path.stat().st_size / 1024:,.0f} KiB")
with log_path.open(encoding="utf-8") as preview_file:
    for line in itertools.islice(preview_file, 4):
        print(line, end="")
```

```text
431 malformed lines injected:
  garbage              100
  status out of range  110
  truncated            116
  unknown method       105
file size: 1,400 KiB
2026-11-06T09:00:01Z 10.0.0.152 "GET /api/products?page=4 HTTP/1.1" 200 216ms
2026-11-06T09:00:01Z 10.0.3.57 "GET /api/products HTTP/1.1" 200 17ms
2026-11-06T09:00:02Z 10.0.2.40 "GET /health HTTP/1.1" 200 1ms
2026-11-06T09:00:03Z 10.0.0.250 "GET /api/products?page=7 HTTP/1.1" 200 129ms
```

> **Note:** 431 out of 20 000 is 2.2%, close to the requested 2%. The exact count is
> whatever the seeded generator produced; change the seed and it changes, which is
> exactly why Step 9 compares against the returned `Counter` rather than a constant.

| Key point | Detail |
| --- | --- |
| Private RNG | `random.Random(seed)` isolates and reproduces the sequence |
| Weighted draws | `rng.choices(population, weights=…)` returns a list |
| Ground truth | The generator reports what it broke |

## Step 2 — Read it lazily with generators

`read_lines` is a generator function: because its body contains `yield`, calling it
runs **none** of that body. It returns a generator object in the `GEN_CREATED` state.
The first `next()` opens the file and runs until the first `yield`, then the
generator freezes (`GEN_SUSPENDED`) with its frame, local variables and open file
intact, waiting for the next request. Line numbers start at 1, as editors show them,
and blank lines are skipped.

The `with` statement inside the generator is what makes this safe. When iteration
ends normally, the `with` block exits and the file is closed. When a consumer stops
early and calls `close()` (or the generator is garbage-collected), Python throws
`GeneratorExit` into the frozen frame at the `yield`, the `with` block exits on the
way out, and the file is still closed. In Node.js the equivalent is an async iterator
over `readline` whose `return()` method closes the stream; here it is synchronous and
needs no event loop.

```python
def read_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, line) for each non-blank line, without newline."""
    with path.open(encoding="utf-8") as log_file:
        for line_number, raw_line in enumerate(log_file, start=1):
            line = raw_line.rstrip("\n")
            if line.strip():
                yield line_number, line


numbered_lines = read_lines(log_path)
print(f"{inspect.isgenerator(numbered_lines)=}")
print(f"{inspect.getgeneratorstate(numbered_lines)=}")
first_number, first_line = next(numbered_lines)
print(first_number)
print(first_line)
print(f"{inspect.getgeneratorstate(numbered_lines)=}")
numbered_lines.close()
print(f"after close(): {inspect.getgeneratorstate(numbered_lines)=}")
```

```text
inspect.isgenerator(numbered_lines)=True
inspect.getgeneratorstate(numbered_lines)='GEN_CREATED'
1
2026-11-06T09:00:01Z 10.0.0.152 "GET /api/products?page=4 HTTP/1.1" 200 216ms
inspect.getgeneratorstate(numbered_lines)='GEN_SUSPENDED'
after close(): inspect.getgeneratorstate(numbered_lines)='GEN_CLOSED'
```

**Proof that it is lazy.** "Lazy" is a claim about memory, so measure memory.
`tracemalloc` records every allocation Python makes; `get_traced_memory()` returns
`(current, peak)` in bytes. Counting the lines through the generator holds one line at
a time, while reading the file eagerly with `read_text().splitlines()` holds the whole
1.4 MB text plus a list of twenty thousand strings. The streaming peak is roughly the
size of the text reader's buffers and stays the same for any file size; the eager peak
grows with the file. Exact byte counts vary by Python version, so the code prints a
comparison rather than the raw numbers.

```python
def traced_peak(thunk: Callable[[], object]) -> tuple[object, int]:
    """Run thunk under tracemalloc; return (result, peak bytes)."""
    tracemalloc.start()
    try:
        result = thunk()
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


streamed_count, streaming_peak = traced_peak(
    lambda: sum(1 for _ in read_lines(log_path))
)
eager_count, eager_peak = traced_peak(
    lambda: len(log_path.read_text(encoding="utf-8").splitlines())
)
print(f"{streamed_count=}, {eager_count=}")
print(
    "streaming peak at least 10x smaller than eager:",
    streaming_peak * 10 < eager_peak,
)
```

```text
streamed_count=20000, eager_count=20000
streaming peak at least 10x smaller than eager: True
```

> **Warning:** a generator is single use. Once `read_lines(log_path)` has been
> exhausted, iterating it again yields nothing; call `read_lines` again for a fresh
> pass.

| Key point | Detail |
| --- | --- |
| Calling a generator | Runs nothing; returns a `GEN_CREATED` object |
| `with` inside a generator | Closes the file on exhaustion or `close()` |
| Memory | Constant for streaming, proportional for eager |

## Step 3 — Parse with `re` and `match`

Parsing happens in two stages, and keeping them apart makes each one simpler:

1. **`re.fullmatch` checks the shape** of the line and extracts the fields with
   named groups. Anything without the right shape (a truncated line, a garbage line)
   fails here.
2. **A `match` statement on `(method, status)` applies the rules** with guards:
   only real HTTP methods, only status codes from 100 to 599.

Every rejection raises `MalformedLineError`, which carries the line number, the raw
line and a short `reason`. It inherits from two classes: a project base class
`LogAnalyzerError`, so a caller can catch "anything this tool raises" in one clause,
and the built-in `ValueError`, so generic code that already handles bad values keeps
working. This dual-inheritance pattern is the one from Unit 1.14.5. Good lines become
an `AccessRecord`, a `NamedTuple`: immutable, compact, and readable by field name.

```python
class LogAnalyzerError(Exception):
    """Base class for errors raised by the log analyzer."""


class MalformedLineError(LogAnalyzerError, ValueError):
    """A log line that could not be parsed."""

    def __init__(self, line_number: int, line: str, reason: str) -> None:
        super().__init__(f"line {line_number}: {reason}")
        self.line_number = line_number
        self.line = line
        self.reason = reason


class AccessRecord(NamedTuple):
    """One parsed access-log line."""

    timestamp: str
    client_ip: str
    method: str
    path: str
    status: int
    latency_ms: int
```

The pattern is written as adjacent raw strings, one per field. The compiler joins
adjacent string literals into one, so this is a single regular expression, but each
field is readable on its own line. `(?P<name>…)` is Python's syntax for a named group
(JavaScript writes `(?<name>…)`), and `found["name"]` reads it back.

`fullmatch` matters here: `re.match` anchors only at the start, so a line with junk
after the latency would still pass. `fullmatch` requires the whole string to match,
like a JavaScript regex wrapped in `^…$`.

The `match` statement then destructures the tuple `(method, status)`. Each `case`
binds names and its `if` guard decides whether the case applies. Cases are tried top
to bottom, so the final `case (method, status):` only runs when both rules passed.
The set of valid methods is a `frozenset`, so membership is a hash lookup and the
constant cannot be modified by accident.

```python
ACCESS_LINE_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r" (?P<client_ip>\d{1,3}(?:\.\d{1,3}){3})"
    r' "(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/1\.1"'
    r" (?P<status>\d{3})"
    r" (?P<latency_ms>\d+)ms"
)
HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)


def parse_access_line(line_number: int, line: str) -> AccessRecord:
    """Parse one line, or raise MalformedLineError with the reason."""
    found = ACCESS_LINE_PATTERN.fullmatch(line)
    if found is None:
        raise MalformedLineError(line_number, line, "unrecognized format")
    match (found["method"], int(found["status"])):
        case (method, _) if method not in HTTP_METHODS:
            raise MalformedLineError(line_number, line, "unknown method")
        case (_, status) if not 100 <= status <= 599:
            raise MalformedLineError(line_number, line, "status out of range")
        case (method, status):
            return AccessRecord(
                found["timestamp"],
                found["client_ip"],
                method,
                found["path"],
                status,
                int(found["latency_ms"]),
            )
```

Try the parser on one line of each kind. The good line becomes a record; each broken
line raises, and the loop prints the error's type and message.

```python
sample_lines = [
    '2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1"'
    " 200 23ms",
    '2026-11-06T09:00:01Z 10.0.1.5 "POST /api/check',
    "<html>502 Bad Gateway</html>",
    '2026-11-06T09:00:02Z 10.0.3.9 "BREW /api/products HTTP/1.1" 200 41ms',
    '2026-11-06T09:00:03Z 10.0.0.4 "GET /health HTTP/1.1" 999 2ms',
]
for sample_number, sample_line in enumerate(sample_lines, start=1):
    try:
        record = parse_access_line(sample_number, sample_line)
    except MalformedLineError as error:
        print(f"{type(error).__name__}: {error}")
    else:
        print(f"{type(record).__name__}: {record.method} {record.path}")
        print(f"  status={record.status}, latency_ms={record.latency_ms}")
```

```text
AccessRecord: GET /api/products/381
  status=200, latency_ms=23
MalformedLineError: line 2: unrecognized format
MalformedLineError: line 3: unrecognized format
MalformedLineError: line 4: unknown method
MalformedLineError: line 5: status out of range
```

> **Note:** `BREW` passes the regex (it is uppercase letters) and `999` passes it too
> (three digits). Only the guards in the `match` reject them. That is the point of the
> two-stage design: the regex stays simple and the rules stay readable.

| Key point | Detail |
| --- | --- |
| `fullmatch` | Anchors both ends; `match` anchors only the start |
| Named groups | `(?P<name>…)`, read with `found["name"]` |
| Guards | `case pattern if condition:` checks after binding |
| Dual base classes | Catchable as `LogAnalyzerError` or `ValueError` |

## Step 4 — Collect `MalformedLineError`s without stopping

One bad line must not abort the analysis of twenty thousand good ones. `parse_records`
is a generator stage that sits between `read_lines` and the aggregation. It catches
**only** `MalformedLineError`, so a genuine bug elsewhere (a `TypeError`, say) still
surfaces instead of being silently counted as a bad line. Each caught error is
appended to a list that the **caller** owns, and the loop moves on.

The `yield` sits in the `else` clause, not inside the `try`. `else` runs only when the
`try` body finished without an exception, so the `except` guards the parsing call and
nothing more. If `yield record` were inside the `try`, an exception thrown into the
generator by its consumer would also be caught here, which is not what we want.

```python
def parse_records(
    numbered_lines: Iterable[tuple[int, str]],
    malformed: list[MalformedLineError],
) -> Iterator[AccessRecord]:
    """Yield parsed records; collect malformed lines into the given list."""
    for line_number, line in numbered_lines:
        try:
            record = parse_access_line(line_number, line)
        except MalformedLineError as error:
            malformed.append(error)
        else:
            yield record


sample_malformed: list[MalformedLineError] = []
sample_records = list(
    parse_records(enumerate(sample_lines, start=1), sample_malformed)
)
print(f"{len(sample_records)} record(s), {len(sample_malformed)} malformed:")
for error in sample_malformed:
    print(f"  line {error.line_number}: {error.reason:<20} {error.line[:40]!r}")
```

```text
1 record(s), 4 malformed:
  line 2: unrecognized format  '2026-11-06T09:00:01Z 10.0.1.5 "POST /api'
  line 3: unrecognized format  '<html>502 Bad Gateway</html>'
  line 4: unknown method       '2026-11-06T09:00:02Z 10.0.3.9 "BREW /api'
  line 5: status out of range  '2026-11-06T09:00:03Z 10.0.0.4 "GET /heal'
```

> **Warning:** the `malformed` list fills up only as the generator is consumed. Right
> after `parse_records(...)` is called it is still empty; read it after the pipeline
> has been drained (here, after `list(...)`).

| Key point | Detail |
| --- | --- |
| Catch narrowly | Only the expected exception type |
| `try`/`except`/`else` | `else` holds the code that must not be guarded |
| Caller-owned list | The generator reports errors without returning them |

## Step 5 — Aggregate status codes, top endpoints and p95 latency

Three helpers come first.

- **`normalize_endpoint`** groups `/api/orders/17` and `/api/orders/4012` as one
  endpoint, `GET /api/orders/{id}`. It drops the query string with `str.partition`
  and replaces every all-digit path segment with `re.sub`. The lookahead `(?=/|$)`
  ensures the digits are a whole segment, without consuming the following slash.
- **`percentile(values, percent)`** uses the *nearest-rank* method: sort, then take
  the value at rank `ceil(percent / 100 * n)`. The p95 latency is the time that 95%
  of requests beat. Unlike the mean, it is not hidden by many fast requests, which is
  why dashboards report it.
- **`status_class`** names a status family with `match` on `status // 100`, the
  integer division from Unit 1.3.

```python
ID_SEGMENT = re.compile(r"/\d+(?=/|$)")


def normalize_endpoint(method: str, path: str) -> str:
    """'GET /api/orders/42?x=1' -> 'GET /api/orders/{id}'."""
    route = ID_SEGMENT.sub("/{id}", path.partition("?")[0])
    return f"{method} {route}"


def percentile(values: Iterable[int], percent: float) -> int:
    """Nearest-rank percentile; ValueError for no values."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of no values")
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def status_class(status: int) -> str:
    """Name the status family."""
    match status // 100:
        case 1:
            return "informational"
        case 2:
            return "success"
        case 3:
            return "redirect"
        case 4:
            return "client error"
        case _:
            return "server error"


print(normalize_endpoint("GET", "/api/orders/42?expand=items"))
print(normalize_endpoint("PUT", "/api/users/7/address"))
print(f"{percentile(range(1, 101), 95)=}, {percentile([120, 15, 30], 50)=}")
print([status_class(status) for status in (101, 204, 304, 404, 503)])
```

```text
GET /api/orders/{id}
PUT /api/users/{id}/address
percentile(range(1, 101), 95)=95, percentile([120, 15, 30], 50)=30
['informational', 'success', 'redirect', 'client error', 'server error']
```

`aggregate` makes **one pass** over the records, so it can consume the lazy pipeline
directly. It fills four containers, each chosen for its job:

| Container | Holds |
| --- | --- |
| `Counter[int]` | Requests per status code |
| `Counter[str]` | Requests per normalized endpoint |
| `defaultdict(list)` | Latencies per endpoint |
| `list[int]` | Every latency, for the overall p95 |

`Counter` removes the "is this key there yet?" check that a JavaScript `Map` counter
needs (`map.set(k, (map.get(k) ?? 0) + 1)`): a missing key reads as `0`.
`defaultdict(list)` does the same for lists, creating an empty list the first time a
key is touched. The result is converted to a plain `dict` before it leaves the
function, so later code that reads a missing endpoint gets a `KeyError` instead of
silently creating an entry.

The latency lists are the only part of the summary that grows with the input; a
production tool would use a streaming quantile sketch instead. `@timer` records how
long the pass takes into `timing_lines`, which Step 7 prints.

```python
class AccessSummary(NamedTuple):
    """Aggregated view of the parsed records."""

    record_count: int
    status_counts: Counter[int]
    endpoint_counts: Counter[str]
    latencies_by_endpoint: dict[str, list[int]]
    all_latencies: list[int]


timing_lines: list[str] = []


@timer(unit="ms", report=timing_lines.append)
def aggregate(records: Iterable[AccessRecord]) -> AccessSummary:
    """Count statuses and endpoints and collect latencies, in one pass."""
    status_counts: Counter[int] = Counter()
    endpoint_counts: Counter[str] = Counter()
    latencies_by_endpoint: defaultdict[str, list[int]] = defaultdict(list)
    all_latencies: list[int] = []
    for record in records:
        endpoint = normalize_endpoint(record.method, record.path)
        status_counts[record.status] += 1
        endpoint_counts[endpoint] += 1
        latencies_by_endpoint[endpoint].append(record.latency_ms)
        all_latencies.append(record.latency_ms)
    return AccessSummary(
        len(all_latencies),
        status_counts,
        endpoint_counts,
        dict(latencies_by_endpoint),
        all_latencies,
    )
```

`top_endpoints` ranks with `sorted` and a tuple key: count descending (by negating
it), then name ascending. Ties therefore come out in a stable, documented order,
rather than in first-seen order as `Counter.most_common` would give. This is the same
pattern as Lab 1.6's `top_k_words`.

```python
def top_endpoints(
    summary: AccessSummary, count: int = 5
) -> list[tuple[str, int, int]]:
    """(endpoint, requests, p95 ms) for the busiest endpoints."""
    ranked = sorted(
        summary.endpoint_counts.items(), key=lambda item: (-item[1], item[0])
    )
    return [
        (
            endpoint,
            requests,
            percentile(summary.latencies_by_endpoint[endpoint], 95),
        )
        for endpoint, requests in ranked[:count]
    ]


sample_summary = aggregate(sample_records)
print(sample_summary.status_counts, top_endpoints(sample_summary))
```

```text
Counter({200: 1}) [('GET /api/products/{id}', 1, 23)]
```

| Key point | Detail |
| --- | --- |
| One pass | Works on a generator; no second read of the file |
| p95, not mean | Shows the slow tail that users notice |
| Tuple sort key | `(-count, name)` gives a deterministic ranking |

## Step 6 — Render an aligned report

Every line of the report is exactly `REPORT_WIDTH` (60) characters, built entirely
from format specs (Unit 1.4.3). The spec after the colon in an f-string field controls
alignment and formatting: `<30` left-aligns in 30 columns, `>30,` right-aligns with a
thousands separator, `.1%` multiplies by 100 and adds a percent sign, and `-<60` pads
with dashes to draw a section rule. `str.center(width, "=")` makes the title bar.
JavaScript has no equivalent mini-language; you would reach for `padStart`,
`padEnd` and `Intl.NumberFormat`.

Example malformed lines are cut to fit by `fit`, which appends an ellipsis. The report
is a **pure function** of its inputs (no printing, no file access), so it is trivial to
test in Step 9.

```python
REPORT_WIDTH = 60


def fit(text: str) -> str:
    """Cut or pad text to exactly REPORT_WIDTH characters."""
    if len(text) > REPORT_WIDTH:
        text = text[: REPORT_WIDTH - 1] + "…"
    return f"{text:<{REPORT_WIDTH}}"


def render_report(
    summary: AccessSummary, malformed: list[MalformedLineError]
) -> str:
    """Build the full text report."""
    total_lines = summary.record_count + len(malformed)
    overall_p95 = percentile(summary.all_latencies, 95)
    lines = [
        "ACCESS LOG REPORT".center(REPORT_WIDTH, "="),
        f"{'Lines read':<30}{total_lines:>30,}",
        f"{'Records parsed':<30}{summary.record_count:>30,}",
        f"{'Malformed lines':<30}{len(malformed):>30,}",
        f"{'Overall p95 latency (ms)':<30}{overall_p95:>30,}",
        f"{'Status codes ':-<{REPORT_WIDTH}}",
        f"{'Status':<8}{'Class':<22}{'Requests':>15}{'Share':>15}",
    ]
    for status, requests in sorted(summary.status_counts.items()):
        share = requests / summary.record_count
        lines.append(
            f"{status:<8}{status_class(status):<22}"
            f"{requests:>15,}{share:>15.1%}"
        )
    lines.append(f"{'Top endpoints ':-<{REPORT_WIDTH}}")
    lines.append(f"{'Endpoint':<34}{'Requests':>13}{'p95 ms':>13}")
    for endpoint, requests, p95_ms in top_endpoints(summary):
        lines.append(f"{endpoint:<34}{requests:>13,}{p95_ms:>13,}")
    lines.append(f"{'Malformed lines by reason ':-<{REPORT_WIDTH}}")
    reason_counts = Counter(error.reason for error in malformed)
    for reason, reason_count in sorted(reason_counts.items()):
        lines.append(f"{reason:<34}{reason_count:>26,}")
    for error in malformed[:3]:
        lines.append(fit(f"  e.g. line {error.line_number}: {error.line!r}"))
    lines.append("=" * REPORT_WIDTH)
    return "\n".join(lines)


print(render_report(sample_summary, sample_malformed))
```

```text
=====================ACCESS LOG REPORT======================
Lines read                                                 5
Records parsed                                             1
Malformed lines                                            4
Overall p95 latency (ms)                                  23
Status codes -----------------------------------------------
Status  Class                        Requests          Share
200     success                             1         100.0%
Top endpoints ----------------------------------------------
Endpoint                               Requests       p95 ms
GET /api/products/{id}                        1           23
Malformed lines by reason ----------------------------------
status out of range                                        1
unknown method                                             1
unrecognized format                                        2
  e.g. line 2: '2026-11-06T09:00:01Z 10.0.1.5 "POST /api/ch…
  e.g. line 3: '<html>502 Bad Gateway</html>'
  e.g. line 4: '2026-11-06T09:00:02Z 10.0.3.9 "BREW /api/pr…
============================================================
```

> **Note:** `f"{text:<{REPORT_WIDTH}}"` nests a replacement field inside the format
> spec, so the width comes from a variable. (Trailing spaces from `fit`'s padding are
> trimmed in the output above for readability; the real lines are all 60 wide.)

| Key point | Detail |
| --- | --- |
| Format specs | `<`, `>`, `^` align; `,` groups; `.1%` percent |
| Nested fields | `{value:<{width}}` takes the width from a variable |
| Pure renderer | Returns a string; printing is the caller's job |

## Step 7 — Run the analysis, timed with a context manager

`analyze_access_log` wires the stages together. Notice that the first line inside it
reads **nothing**: `read_lines(path)` creates a generator, `parse_records(...)` wraps
it in another, and only when `aggregate` asks for the first record does the file open.
The whole file then streams through `read_lines → parse_records → aggregate` in a
single pass, one line at a time.

With `strict=True`, the function still collects **every** malformed line first, then
raises them together as one `ExceptionGroup` (Unit 1.14.6). A caller sees all the
problems at once instead of fixing the first, re-running, and discovering the second.
This is the job JavaScript's `AggregateError` does, but Python adds a way to handle
the group by type (`except*`, Step 8).

```python
def analyze_access_log(
    path: Path, *, strict: bool = False
) -> tuple[AccessSummary, list[MalformedLineError]]:
    """Stream the log through the pipeline; optionally fail on bad lines."""
    malformed: list[MalformedLineError] = []
    summary = aggregate(parse_records(read_lines(path), malformed))
    if strict and malformed:
        raise ExceptionGroup(
            f"{len(malformed)} malformed lines in {path.name}", malformed
        )
    return summary, malformed
```

The run itself sits inside `with Timer(...)`. The `Timer` reports when the block
exits, and the `@timer` on `aggregate` reports when that call returns, both into
`timing_lines`.

```python
timing_lines.clear()
with Timer("full analysis", report=timing_lines.append):
    access_summary, malformed_lines = analyze_access_log(log_path)
    report_text = render_report(access_summary, malformed_lines)

print(report_text)
print("\n".join(timing_lines))
```

```text
=====================ACCESS LOG REPORT======================
Lines read                                            20,000
Records parsed                                        19,569
Malformed lines                                          431
Overall p95 latency (ms)                                 225
Status codes -----------------------------------------------
Status  Class                        Requests          Share
200     success                        15,690          80.2%
201     success                           982           5.0%
204     success                           384           2.0%
304     redirect                          612           3.1%
400     client error                      575           2.9%
401     client error                      187           1.0%
404     client error                      580           3.0%
429     client error                      197           1.0%
500     server error                      164           0.8%
502     server error                       98           0.5%
503     server error                      100           0.5%
Top endpoints ----------------------------------------------
Endpoint                               Requests       p95 ms
GET /api/products                         5,904          120
GET /api/products/{id}                    4,798           74
POST /api/cart/items                      2,417          181
GET /health                               2,051            6
GET /api/orders/{id}                      1,928          245
Malformed lines by reason ----------------------------------
status out of range                                      110
unknown method                                           105
unrecognized format                                      216
  e.g. line 64: '-'
  e.g. line 127: '2026-11-06T09:01:46Z 10.0.2.31 "GET /api/…
  e.g. line 232: '-'
============================================================
aggregate took 59.127 ms
full analysis took 63.53 ms
```

> **Note:** the report is identical on every run because the log is seeded. The two
> timing lines at the end vary by machine and by run. Notice also that the timings
> are almost equal: nearly all the work (reading, parsing, counting) happens inside
> `aggregate`, because that is where the lazy pipeline is actually pulled.

Read the report against the design. 216 "unrecognized format" lines is exactly the
116 truncated plus 100 garbage lines that Step 1 injected, and the other two reasons
match their injected counts. `/api/checkout` has a high typical latency but is not in
the top five by request count, so it does not appear; `GET /health` is busy but its
p95 is 6 ms.

| Key point | Detail |
| --- | --- |
| Lazy wiring | Composing generators reads nothing until pulled |
| `ExceptionGroup` | Raise many errors as one |
| `with Timer` | Timing wraps the code without changing it |

## Step 8 — Upload with `@retry`, and strict mode with `except*`

The finished report is sent to a (simulated) report server that drops the first two
connections, as real networks do during a deploy. `upload_report` is wrapped in
`@retry`, configured to retry **only** on `ConnectionError` and `TimeoutError`. A
`ValueError` from a bug would not be retried, which is the right behaviour: retrying
a deterministic failure only delays the error. `sleep=upload_delays.append` records
the backoff delays instead of waiting, so the demonstration is instant and testable;
in production you would keep the default `time.sleep`.

```python
class FlakyReportServer:
    """Refuses the first `failures` uploads, then stores the report."""

    def __init__(self, failures: int, destination: Path) -> None:
        self.failures_left = failures
        self.destination = destination
        self.attempts = 0

    def receive(self, report: str) -> int:
        """Store the report; return its size, or raise ConnectionError."""
        self.attempts += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise ConnectionError(f"connection reset (attempt {self.attempts})")
        self.destination.write_text(report + "\n", encoding="utf-8")
        return self.destination.stat().st_size


report_server = FlakyReportServer(
    failures=2, destination=scratch_dir / "phase1_log_report.txt"
)
upload_delays: list[float] = []


@retry(
    times=4,
    exceptions=(ConnectionError, TimeoutError),
    first_delay=0.05,
    sleep=upload_delays.append,
)
def upload_report(report: str) -> str:
    """Send the report to the server (flaky)."""
    return f"uploaded {report_server.receive(report):,} bytes"


print(upload_report(report_text))
print(f"{report_server.attempts=}, {upload_delays=}")
```

```text
uploaded 2,015 bytes
report_server.attempts=3, upload_delays=[0.05, 0.1]
```

Two failures, then success on the third attempt; the delays double each time
(`0.05`, then `0.1`), which is the exponential backoff.

**Strict mode.** A pipeline that must not accept bad input runs with `strict=True`.
The caller handles the whole group with `except* MalformedLineError`: one clause
receives **every** malformed line at once, as a smaller `ExceptionGroup` whose
`.exceptions` tuple holds them. If the group also contained some *other* exception
type, this clause would not swallow it; it would be re-raised after the `except*`
clauses run. That is the key difference from a plain `except ExceptionGroup`, which
would catch everything regardless of what is inside.

```python
try:
    analyze_access_log(log_path, strict=True)
except* MalformedLineError as malformed_group:
    reasons = Counter(error.reason for error in malformed_group.exceptions)
    print(f"strict run rejected: {malformed_group.message}")
    print("by reason:")
    for reason, reason_count in sorted(reasons.items()):
        print(f"  {reason:<20} {reason_count}")
    first_problem = malformed_group.exceptions[0]
    print(f"first problem: {first_problem} -> {first_problem.line[:45]!r}")
```

```text
strict run rejected: 431 malformed lines in phase1_access.log
by reason:
  status out of range  110
  unknown method       105
  unrecognized format  216
first problem: line 64: unrecognized format -> '-'
```

> **Warning:** inside an `except*` clause the bound name is always an
> `ExceptionGroup`, never a bare exception, even if only one error matched. Read the
> individual errors from `.exceptions`.

| Key point | Detail |
| --- | --- |
| Retry narrowly | Only transient errors (`ConnectionError`, …) |
| Injectable `sleep` | Tests record delays instead of waiting |
| `except*` | Handles matching members; re-raises the rest |

## Step 9 — Self-check

The project's own tests use the shared `run_checks`. Good tests tie the output back
to the input rather than to magic numbers: every line is either a record or a
malformed line; the malformed reasons match what Step 1 says it injected (truncated
and garbage lines both fail the regex, so both report `"unrecognized format"`); the
status counts add up; and the report is aligned. `same_seed_same_file` proves the
generator is deterministic by hashing three small files with `hashlib.sha256`.

```python
EXPECTED_REASON = {
    "truncated": "unrecognized format",
    "garbage": "unrecognized format",
    "unknown method": "unknown method",
    "status out of range": "status out of range",
}


def expected_reasons(injected: Counter[str]) -> Counter[str]:
    """Translate injected kinds into the reasons the parser should report."""
    reasons: Counter[str] = Counter()
    for kind, kind_count in injected.items():
        reasons[EXPECTED_REASON[kind]] += kind_count
    return reasons


def same_seed_same_file() -> tuple[bool, bool]:
    """(seed 42 twice gives identical bytes, seed 7 gives different bytes)."""
    digests = []
    for run_number, seed in enumerate((42, 42, 7)):
        check_path = scratch_dir / f"phase1_access_check_{run_number}.log"
        write_synthetic_log(check_path, 500, seed=seed)
        digests.append(hashlib.sha256(check_path.read_bytes()).hexdigest())
        check_path.unlink()
    return digests[0] == digests[1], digests[0] != digests[2]
```

Run the checks:

```python
run_checks(
    [
        ("deterministic generator", same_seed_same_file, (True, True)),
        (
            "every line accounted for",
            lambda: access_summary.record_count + len(malformed_lines),
            LOG_LINE_COUNT,
        ),
        (
            "reasons match the injected damage",
            lambda: Counter(error.reason for error in malformed_lines),
            expected_reasons(injected_kinds),
        ),
        (
            "status counts add up",
            lambda: sum(access_summary.status_counts.values()),
            access_summary.record_count,
        ),
        (
            "percentile",
            lambda: (percentile(range(1, 101), 95), percentile([5], 95)),
            (95, 5),
        ),
        (
            "percentile of nothing",
            lambda: raised_error_name(lambda: percentile([], 95)),
            "ValueError",
        ),
        (
            "normalize_endpoint",
            lambda: normalize_endpoint("DELETE", "/api/cart/items/12?force=1"),
            "DELETE /api/cart/items/{id}",
        ),
        (
            "parse error type",
            lambda: raised_error_name(lambda: parse_access_line(1, "garbage")),
            "MalformedLineError",
        ),
        (
            "report aligned",
            lambda: {len(line) for line in report_text.splitlines()},
            {REPORT_WIDTH},
        ),
        (
            "upload retried twice",
            lambda: (report_server.attempts, upload_delays),
            (3, [0.05, 0.1]),
        ),
        (
            "strict mode raises a group",
            lambda: raised_error_name(
                lambda: analyze_access_log(log_path, strict=True)
            ),
            "ExceptionGroup",
        ),
        (
            "pipeline is lazy",
            lambda: inspect.isgenerator(parse_records([], [])),
            True,
        ),
    ]
)
```

```text
PASS  deterministic generator
PASS  every line accounted for
PASS  reasons match the injected damage
PASS  status counts add up
PASS  percentile
PASS  percentile of nothing
PASS  normalize_endpoint
PASS  parse error type
PASS  report aligned
PASS  upload retried twice
PASS  strict mode raises a group
PASS  pipeline is lazy
12/12 checks passed
```

| Key point | Detail |
| --- | --- |
| Test against the input | Compare with the generator's own `Counter` |
| Thunks | `lambda: …` delays the call so `run_checks` can catch errors |
| Pure functions | The renderer and helpers need no fixtures |

## Ideas to extend it

- **Compressed logs.** Read a `.gz` file with `gzip.open(path, "rt")` inside
  `read_lines`. Nothing else changes, because every stage takes an iterable.
- **A time filter.** Add a `--since` filter as one more generator stage between
  `read_lines` and `parse_records` (or between `parse_records` and `aggregate`).
- **Traffic over time.** Report requests per minute with
  `Counter(record.timestamp[:16] for record in records)`.
- **Constant memory.** Replace the latency lists with a fixed-size reservoir sample,
  so memory stays constant however long the log is.
- **Several files.** Chain logs from a rotated set with `itertools.chain`, keeping
  the line numbers per file.
- **A command-line tool.** Wrap `analyze_access_log` in `argparse`, print the report,
  and exit with status 1 in strict mode when the group is raised.

## Phase 1 review — 30 predict-the-output questions

Thirty short snippets, at least two from every unit of the phase. For each one, decide
what it prints **before** opening the answer. If a question surprises you, go back to
the unit it names.

| Unit | Questions |
| --- | --- |
| [1.1](unit-1-1-how-python-executes-code.md) | 1–2 |
| [1.2](unit-1-2-objects-names-and-mutability.md) | 3–4 |
| [1.3](unit-1-3-numeric-and-boolean-data-types.md) | 5–6 |
| [1.4](unit-1-4-text-and-binary-data-types.md) | 7–8 |
| [1.5](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md) | 9–11 |
| [1.6](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md) | 12–14 |
| [1.7](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md) | 15–16 |
| [1.8](unit-1-8-operators-expressions-and-control-flow.md) | 17–18 |
| [1.9](unit-1-9-iteration-comprehensions-and-built-in-functions.md) | 19–20 |
| [1.10](unit-1-10-functions-definition-and-arguments.md) | 21–22 |
| [1.11](unit-1-11-scope-namespaces-and-closures.md) | 23–24 |
| [1.12](unit-1-12-decorators-functools-and-the-call-stack.md) | 25–26 |
| [1.13](unit-1-13-iterators-generators-and-itertools.md) | 27–28 |
| [1.14](unit-1-14-exceptions-and-context-managers.md) | 29–30 |

### Question 1 — Unit 1.1

```python
def checkout_total() -> int:
    return subtotal + delivery_fee


subtotal = 400
delivery_fee = 40
print(checkout_total())
```

<details><summary>Answer</summary>

```text
440
```

Compiling the `def` only creates the function; global names inside it are looked up
when it **runs** (`LOAD_GLOBAL`), and by then both exist.

</details>

### Question 2 — Unit 1.1

```python
print(eval("[n * n for n in range(4)]"))
try:
    eval("total = 5")
except SyntaxError:
    print("SyntaxError")
```

<details><summary>Answer</summary>

```text
[0, 1, 4, 9]
SyntaxError
```

`eval` accepts only an **expression**; an assignment is a statement. Use `exec` for
statements, or `:=` for an assignment expression.

</details>

### Question 3 — Unit 1.2

```python
prices = [100, 200]
alias = prices
alias += [300]
alias = alias + [400]
print(prices, alias)
```

<details><summary>Answer</summary>

```text
[100, 200, 300] [100, 200, 300, 400]
```

`+=` on a list mutates it in place, so both names see the change; `alias + [400]`
builds a **new** list and rebinds only `alias`.

</details>

### Question 4 — Unit 1.2

```python
def add_item(cart: list[str], item: str) -> None:
    cart.append(item)
    cart = ["reset"]


basket = ["rice"]
add_item(basket, "dal")
print(basket)
```

<details><summary>Answer</summary>

```text
['rice', 'dal']
```

The parameter is a second name for the caller's list: `append` mutates that object,
while `cart = [...]` only rebinds the local name (call by object reference).

</details>

### Question 5 — Unit 1.3

```python
print(0.1 + 0.2 == 0.3, round(2.5), round(3.5), -7 // 2, -7 % 2)
```

<details><summary>Answer</summary>

```text
False 2 4 -4 1
```

Binary floats cannot store 0.1 exactly; `round` rounds halves to even (banker's
rounding); `//` floors toward minus infinity, and `%` takes the sign of the divisor.

</details>

### Question 6 — Unit 1.3

```python
from decimal import Decimal

print(
    True + True,
    isinstance(True, int),
    Decimal("0.1") * 3 == Decimal("0.3"),
    bool("False"),
)
```

<details><summary>Answer</summary>

```text
2 True True True
```

`bool` is a subclass of `int` (`True == 1`); a `Decimal` built from a string is exact;
any non-empty string is truthy, including `"False"`.

</details>

### Question 7 — Unit 1.4

```python
word = "naïve"
print(len(word), len(word.encode("utf-8")), word[::-1].upper())
```

<details><summary>Answer</summary>

```text
5 6 EVÏAN
```

`len` counts code points (5); UTF-8 needs two bytes for `ï`, so 6 bytes; slicing and
`upper` work on code points too. A decomposed `ï` (`i` plus a combining mark) would
make the length 6: see 1.4.4.

</details>

### Question 8 — Unit 1.4

```python
print(
    "a,b,,c".split(","),
    "a b  c".split(),
    "-".join("abc"),
    repr("Hello"[10:]),
)
```

<details><summary>Answer</summary>

```text
['a', 'b', '', 'c'] ['a', 'b', 'c'] a-b-c ''
```

With a separator, `split` keeps empty fields; with no argument it splits on runs of
whitespace; `join` iterates the string; slicing past the end returns `''` instead of
raising.

</details>

### Question 9 — Unit 1.5

```python
grid = [[0] * 2] * 2
grid[0][0] = 9
print(grid)
```

<details><summary>Answer</summary>

```text
[[9, 0], [9, 0]]
```

The outer `* 2` copies the **reference** to one inner list, so both rows are the same
object. Build rows with `[[0] * 2 for _ in range(2)]`.

</details>

### Question 10 — Unit 1.5

```python
order = ("tea", ["cup"])
try:
    order[1] += ["saucer"]
except TypeError as error:
    print(type(error).__name__)
print(order)
```

<details><summary>Answer</summary>

```text
TypeError
('tea', ['cup', 'saucer'])
```

`+=` first extends the list in place (that succeeds), then tries to store the result
back into the tuple slot (that fails). The mutation has already happened.

</details>

### Question 11 — Unit 1.5

```python
names = ["bea", "Al", "cy", "Bo"]
print(sorted(names))
print(sorted(names, key=str.lower))
print(names.sort())
```

<details><summary>Answer</summary>

```text
['Al', 'Bo', 'bea', 'cy']
['Al', 'bea', 'Bo', 'cy']
None
```

Uppercase letters sort before lowercase by code point; `key=str.lower` compares
case-insensitively; `list.sort()` sorts in place and returns `None`.

</details>

### Question 12 — Unit 1.6

```python
labels = {1: "int", 1.0: "float", True: "bool"}
print(labels)
```

<details><summary>Answer</summary>

```text
{1: 'bool'}
```

`1`, `1.0` and `True` are equal and hash the same, so they are one key. The **first**
key object is kept, the **last** value wins.

</details>

### Question 13 — Unit 1.6

```python
prices = {"tea": 10, "coffee": 20}
prices["tea"] = 15
prices |= {"juice": 30, "tea": 5}
print(list(prices), prices["tea"])
```

<details><summary>Answer</summary>

```text
['tea', 'coffee', 'juice'] 5
```

Dicts keep insertion order; updating an existing key (by assignment or `|=`) changes
its value but **not** its position.

</details>

### Question 14 — Unit 1.6

```python
from collections import Counter

letters = Counter("mississippi")
print(letters.most_common(2), letters["z"], "z" in letters)
```

<details><summary>Answer</summary>

```text
[('i', 4), ('s', 4)] 0 False
```

Ties in `most_common` keep first-seen order (`i` appears before `s`); a missing key
reads as `0` but is **not** inserted.

</details>

### Question 15 — Unit 1.7

```python
order = {"items": ["pen"], "total": 10}
snapshot = order.copy()
snapshot["items"].append("ink")
snapshot["total"] = 25
print(order)
```

<details><summary>Answer</summary>

```text
{'items': ['pen', 'ink'], 'total': 10}
```

A shallow copy is a new dict holding the **same** values: the shared list sees the
`append`, while rebinding `total` in the copy does not touch the original.

</details>

### Question 16 — Unit 1.7

```python
import copy

shared = [1]
pair = [shared, shared]
clone = copy.deepcopy(pair)
clone[0].append(2)
print(clone, clone[0] is clone[1], pair)
```

<details><summary>Answer</summary>

```text
[[1, 2], [1, 2]] True [[1], [1]]
```

`deepcopy` copies the inner list once and uses its `memo` to reuse that copy, so the
clone keeps the original's sharing structure while sharing nothing with the original.

</details>

### Question 17 — Unit 1.8

```python
print(0 or [] or "default", 0 and 1 / 0, None or 0, [] and "never")
```

<details><summary>Answer</summary>

```text
default 0 0 []
```

`or` returns the first truthy operand (or the last one); `and` returns the first falsy
operand (or the last one) and short-circuits, so `1 / 0` never runs.

</details>

### Question 18 — Unit 1.8

```python
def describe(command: object) -> str:
    match command:
        case [action]:
            return f"one: {action}"
        case [action, *rest]:
            return f"many: {action} +{len(rest)}"
        case str():
            return "text"
        case _:
            return "other"


print(
    describe("go"),
    describe(["go"]),
    describe(("go", "fast", "now")),
    describe({}),
)
```

<details><summary>Answer</summary>

```text
text one: go many: go +2 other
```

Sequence patterns match lists and tuples but deliberately **not** strings, so `"go"`
falls through to `str()`; a dict is not a sequence at all.

</details>

### Question 19 — Unit 1.9

```python
squares = (n * n for n in range(4))
print(sum(squares), sum(squares))
print(list(zip("ab", [1, 2, 3], strict=False)))
```

<details><summary>Answer</summary>

```text
14 0
[('a', 1), ('b', 2)]
```

A generator expression is single use, so the second `sum` sees nothing; `zip` stops at
the shortest input (unless `strict=True`).

</details>

### Question 20 — Unit 1.9

```python
print(any([]), all([]), max([], default="none"), list(enumerate("xy", 1)))
```

<details><summary>Answer</summary>

```text
False True none [(1, 'x'), (2, 'y')]
```

`any` of nothing is `False`, `all` of nothing is `True` (there is no counter-example);
`max` of an empty iterable needs `default`; `enumerate`'s second argument is the
start number.

</details>

### Question 21 — Unit 1.10

```python
def add_tag(tag: str, tags: list[str] = []) -> list[str]:
    tags.append(tag)
    return tags


print(add_tag("a"), add_tag("b"))
```

<details><summary>Answer</summary>

```text
['a', 'b'] ['a', 'b']
```

The default list is created **once**, at `def` time, and shared by every call. Both
calls return that same list, and `print` shows it after both appends.

</details>

### Question 22 — Unit 1.10

```python
def book_room(room_number: int, /, guest: str, *, nights: int = 1) -> str:
    return f"{room_number}:{guest}:{nights}"


print(book_room(101, guest="Asha", nights=2))
print(book_room(102, "Ravi"))
try:
    book_room(room_number=103, guest="Meena")
except TypeError:
    print("TypeError")
```

<details><summary>Answer</summary>

```text
101:Asha:2
102:Ravi:1
TypeError
```

Parameters before `/` are positional-only, so `room_number=` is rejected; `guest` can
be passed either way; `nights` (after `*`) only by keyword.

</details>

### Question 23 — Unit 1.11

```python
multipliers = [lambda x: x * factor for factor in range(3)]
print([multiply(10) for multiply in multipliers])
```

<details><summary>Answer</summary>

```text
[20, 20, 20]
```

Each lambda closes over the **variable** `factor`, not its value at creation; when
they run, the loop has finished with `factor == 2` (late binding). Fix it with a
default: `lambda x, factor=factor: x * factor`.

</details>

### Question 24 — Unit 1.11

```python
visits = 0


def record_visit() -> None:
    visits += 1


try:
    record_visit()
except UnboundLocalError:
    print("UnboundLocalError")
print(visits)
```

<details><summary>Answer</summary>

```text
UnboundLocalError
0
```

Assigning to `visits` anywhere in the function makes it **local** for the whole body
(decided at compile time), so `visits += 1` reads a local that has no value yet.
`global visits` (or better, a parameter) fixes it.

</details>

### Question 25 — Unit 1.12

```python
def tag(label):
    def decorator(func):
        def wrapper():
            return f"<{label}>{func()}</{label}>"
        return wrapper
    return decorator


@tag("b")
@tag("i")
def greet():
    return "hi"


print(greet(), greet.__name__)
```

<details><summary>Answer</summary>

```text
<b><i>hi</i></b> wrapper
```

Decorators apply bottom-up (`tag("b")(tag("i")(greet))`), so the outer tag wraps the
inner one. Without `functools.wraps`, the result keeps the wrapper's name.

</details>

### Question 26 — Unit 1.12

```python
import functools


@functools.lru_cache(maxsize=128)
def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)


print(fib(10), fib.cache_info())
```

<details><summary>Answer</summary>

```text
55 CacheInfo(hits=8, misses=11, maxsize=128, currsize=11)
```

Each of `fib(0)` … `fib(10)` is computed once (11 misses); for `n` from 3 to 10, the
`fib(n - 2)` call finds the value its sibling branch just cached (8 hits).

</details>

### Question 27 — Unit 1.13

```python
def countdown(start: int):
    print("starting")
    while start > 0:
        yield start
        start -= 1


launch = countdown(2)
print("created")
print(list(launch), list(launch))
```

<details><summary>Answer</summary>

```text
created
starting
[2, 1] []
```

Calling a generator function runs none of its body; the first `next()` (inside
`list`) starts it. A generator is single use, so the second `list` is empty.

</details>

### Question 28 — Unit 1.13

```python
import itertools

print([(key, len(list(group))) for key, group in itertools.groupby("aabaa")])
print(list(itertools.islice(itertools.count(10, 5), 3)))
```

<details><summary>Answer</summary>

```text
[('a', 2), ('b', 1), ('a', 2)]
[10, 15, 20]
```

`groupby` groups **consecutive** equal items only (sort first to group globally);
`islice` takes a finite slice of an infinite `count`.

</details>

### Question 29 — Unit 1.14

```python
def checkout() -> str:
    try:
        print("try")
        return "from try"
    except ValueError:
        return "from except"
    else:
        return "from else"
    finally:
        print("finally")


print(checkout())
```

<details><summary>Answer</summary>

```text
try
finally
from try
```

`else` runs only when the `try` body finishes **without** an exception **and** without
leaving through `return`, `break` or `continue`; `finally` runs on the way out, before
the caller receives the value.

</details>

### Question 30 — Unit 1.14

```python
try:
    try:
        {}["sku"]
    except KeyError:
        raise ValueError("bad order") from None
except ValueError as outer:
    print(
        repr(outer.__cause__),
        repr(outer.__context__),
        outer.__suppress_context__,
    )
```

<details><summary>Answer</summary>

```text
None KeyError('sku') True
```

`from None` sets no cause and only **hides** the context: `__context__` still holds
the `KeyError`, and `__suppress_context__` tells the traceback printer not to show it.

</details>

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| Generator pipeline | Stages pull one item at a time | Async iterators over streams |
| Seeded `Random` | Reproducible data and tests | A seeded PRNG library |
| `re.fullmatch` | Whole-string match, named groups | `/^(?<name>…)$/` |
| `match` + guards | Destructure, then check rules | `switch` plus `if` |
| Collect, don't crash | Catch narrowly, keep the error | `try`/`catch` in a loop |
| `Counter` | Counting without key checks | `Map` with `?? 0` |
| Format specs | Aligned text without a library | `padStart` / `Intl` |
| `@retry` | Resilience added at definition | `p-retry` wrapper |
| `ExceptionGroup` | Many errors raised as one | `AggregateError` |
| `except*` | Handle a group by member type | No equivalent |

## Further reading

- [`re` — Regular expression operations](https://docs.python.org/3/library/re.html)
- [The `match` statement](https://docs.python.org/3/reference/compound_stmts.html#the-match-statement)
- [`collections.Counter`](https://docs.python.org/3/library/collections.html#collections.Counter)
- [Generator functions](https://docs.python.org/3/howto/functional.html#generators)
- [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html)
- [Exception groups and `except*`](https://docs.python.org/3/tutorial/errors.html#raising-and-handling-multiple-unrelated-exceptions)
- [Format specification mini-language](https://docs.python.org/3/library/string.html#formatspec)
- [PEP 634 — Structural pattern matching](https://peps.python.org/pep-0634/)
- [PEP 654 — Exception groups and `except*`](https://peps.python.org/pep-0654/)
- [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/)

[← Previous](unit-1-14-exceptions-and-context-managers.md) · [Index](README.md) · [Next →](cheatsheet.md)
