"""Phase 1 Project — Log Analyzer, closing with 30 predict-the-output questions."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

PROJECT_SETUP_SOURCE = '''
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


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.version_info[:2]=}")
'''

HELPERS_SOURCE = '''
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
        raise ValueError(f"unit must be one of {sorted(TIME_UNITS)}, got {unit!r}")

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


def retry(
    times: int = 3,
    *,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    first_delay: float = 0.1,
    backoff: float = 2.0,
    sleep: Callable[[float], object] = time.sleep,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry on the listed exceptions, sleeping first_delay * backoff**n in between."""
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


class Timer:
    """Time a with block and report "<label> took <ms> ms"."""

    def __init__(self, label: str, report: Callable[[str], object] = print) -> None:
        self.label = label
        self.report = report
        self.elapsed_seconds = 0.0

    def __enter__(self) -> Timer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_seconds = time.perf_counter() - self._started
        self.report(f"{self.label} took {self.elapsed_seconds * 1000:.2f} ms")
'''


def _overview_cells() -> list[NotebookNode]:
    """Project opener, setup and reused helpers."""
    return [
        md(
            """
            ## Phase 1 Project — Log Analyzer

            Build a small but complete tool that analyzes a web server's access log, using only
            what Phase 1 covered. The pipeline:

            ```mermaid
            graph LR
                A[write_synthetic_log] --> B[read_lines]
                B --> C[parse_records]
                C -->|AccessRecord| D[aggregate]
                C -->|MalformedLineError| E[malformed list]
                D --> F[render_report]
                E --> F
                F --> G["upload_report (@retry)"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            write_synthetic_log -> read_lines -> parse_records --AccessRecord--------> aggregate
                                                      |                                    |
                                                      +--MalformedLineError--> list         |
                                                                                |          v
                                                                                +--> render_report
                                                                                         |
                                                                                         v
                                                                              upload_report (@retry)
            ```

            </details>

            | Step | Requirement | Phase 1 tools |
            | --- | --- | --- |
            | 1 | Generate a seeded synthetic access log, with malformed lines | `random.Random(seed)` (1.3), f-strings (1.4), `with open` (1.14) |
            | 2 | Read it lazily with generators | generator functions (1.13), `enumerate` (1.9) |
            | 3 | Parse with `re` and `match` | named groups, `re.fullmatch` (1.4), `match` with guards (1.8), `NamedTuple` (1.5) |
            | 4 | Collect `MalformedLineError`s without stopping | custom exceptions (1.14.5), `try` / `except` / `else` (1.14.2) |
            | 5 | Status codes, top endpoints, p95 latency | `Counter`, `defaultdict` (1.6), `sorted` with a key (1.5), `re.sub`, `@timer` (1.12) |
            | 6 | Print an aligned report | format specs (1.4.3) |
            | 7 | Time the whole run with a context manager | `Timer` (1.14.9) |
            | 8 | Wrap a flaky `upload_report()` in `@retry`; strict mode | `retry` (1.12.6), `ExceptionGroup` and `except*` (1.14.6) |
            | 9 | Self-check | `run_checks` (shared setup) |

            The setup cell imports what the project needs, so this section runs on its own after
            the shared setup cell.
            """
        ),
        code(PROJECT_SETUP_SOURCE),
        md(
            """
            **Reused helpers.** These three are copied from earlier units, unchanged, so the
            project does not depend on cells far above (Lab 1.12's stubs also shadow the names
            `timer` and `retry`):

            | Helper | From | Used for |
            | --- | --- | --- |
            | `timer(unit=, report=)` | 1.12.3 | timing `aggregate` |
            | `retry(times, exceptions=, first_delay=, backoff=, sleep=)` | 1.12.6 | the flaky upload |
            | `Timer(label, report=)` | 1.14.9 | timing the whole run |
            """
        ),
        code(HELPERS_SOURCE),
    ]


def _generate_cells() -> list[NotebookNode]:
    """Step 1: the synthetic log."""
    return [
        md(
            """
            ### Step 1 — Generate a seeded synthetic access log

            Each well-formed line has six fields:

            ```text
            2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1" 200 23ms
            timestamp            client IP  method path              protocol  status latency
            ```

            The generator uses its own `random.Random(seed)` instance (not the global `random`),
            so the same seed always gives the same file and nothing else in the notebook is
            affected. Endpoints, status codes and latencies are drawn with weights; latency is
            log-normal around a typical value per endpoint (real latencies have a long tail), and
            5xx responses are slower. About 2% of lines are deliberately broken in one of four
            ways. The function returns a `Counter` of what it injected, so the analysis can be
            checked against it.
            """
        ),
        code(
            '''
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
            MALFORMED_KINDS = ("truncated", "garbage", "unknown method", "status out of range")
            GARBAGE_LINES = ("-", "<html>502 Bad Gateway</html>", "Connection reset by peer", "GET /")


            def well_formed_line(rng: random.Random, timestamp: dt.datetime) -> str:
                """One valid access-log line drawn from the weighted tables."""
                method, template, _, typical_ms = rng.choices(ENDPOINTS, weights=[e[2] for e in ENDPOINTS])[0]
                path = template.replace("{id}", str(rng.randint(1, 5_000)))
                if template == "/api/products" and rng.random() < 0.3:
                    path += f"?page={rng.randint(2, 9)}"
                status = rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]
                latency_ms = max(1, round(rng.lognormvariate(math.log(typical_ms), 0.6)))
                if status >= 500:
                    latency_ms *= 5
                client_ip = f"10.0.{rng.randint(0, 3)}.{rng.randint(1, 254)}"
                stamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                return f'{stamp} {client_ip} "{method} {path} HTTP/1.1" {status} {latency_ms}ms'
            '''
        ),
        md(
            """
            `break_line` produces the four kinds of damage: a line cut short (a crashed writer),
            a garbage line (an upstream error page), an unknown HTTP method, and an impossible
            status code. The last two still *look* like log lines, so only the `match` step can
            reject them.
            """
        ),
        code(
            '''
            def break_line(rng: random.Random, line: str, kind: str) -> str:
                """Damage a valid line in the given way."""
                match kind:
                    case "truncated":
                        return line[: rng.randint(10, len(line) - 6)]
                    case "garbage":
                        return rng.choice(GARBAGE_LINES)
                    case "unknown method":
                        return re.sub(r'"[A-Z]+ ', f'"{rng.choice(["FETCH", "BREW"])} ', line, count=1)
                    case "status out of range":
                        return re.sub(r'" \\d{3} ', f'" {rng.choice(["000", "999"])} ', line, count=1)
                    case _:
                        raise ValueError(f"unknown kind: {kind!r}")


            def write_synthetic_log(
                path: Path, line_count: int, *, seed: int = 42, malformed_rate: float = 0.02
            ) -> Counter[str]:
                """Write line_count lines to path; return how many of each malformed kind were written."""
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
                        log_file.write(line + "\\n")
                return injected
            '''
        ),
        md(
            """
            Write 20 000 lines to the scratch folder and look at the first few, and at the file
            size. Because the generator is seeded, these lines are identical on every run.
            """
        ),
        code(
            """
            LOG_LINE_COUNT = 20_000
            log_path = scratch_dir / "phase1_access.log"
            injected_kinds = write_synthetic_log(log_path, LOG_LINE_COUNT, seed=42)

            injected_total = sum(injected_kinds.values())
            print(f"{injected_total} malformed lines injected: {dict(sorted(injected_kinds.items()))}")
            print(f"file size: {log_path.stat().st_size / 1024:,.0f} KiB")
            with log_path.open(encoding="utf-8") as preview_file:
                for line in itertools.islice(preview_file, 4):
                    print(line, end="")
            """
        ),
    ]


def _reading_cells() -> list[NotebookNode]:
    """Step 2: lazy reading."""
    return [
        md(
            """
            ### Step 2 — Read it lazily with generators

            `read_lines` is a generator function (Unit 1.13): calling it does nothing until the
            first `next()`, then it opens the file and yields one `(line_number, line)` pair at a
            time. Line numbers start at 1 (as editors show them) and blank lines are skipped. The
            `with` inside the generator closes the file when iteration ends, or when the
            generator is closed or garbage-collected early.
            """
        ),
        code(
            '''
            def read_lines(path: Path) -> Iterator[tuple[int, str]]:
                """Yield (line_number, line) for each non-blank line, without the newline."""
                with path.open(encoding="utf-8") as log_file:
                    for line_number, raw_line in enumerate(log_file, start=1):
                        line = raw_line.rstrip("\\n")
                        if line.strip():
                            yield line_number, line


            numbered_lines = read_lines(log_path)
            print(f"{inspect.isgenerator(numbered_lines)=}, {inspect.getgeneratorstate(numbered_lines)=}")
            print(next(numbered_lines))
            print(f"{inspect.getgeneratorstate(numbered_lines)=}")
            numbered_lines.close()
            print(f"after close(): {inspect.getgeneratorstate(numbered_lines)=}")
            '''
        ),
        md(
            """
            **Proof that it is lazy.** Counting the lines through the generator holds one line at
            a time; reading the file eagerly (`read_text().splitlines()`) holds all of it. The
            cell measures both peaks with `tracemalloc`. The streaming peak (roughly the text
            reader's buffers, about 150 kB here) stays the same for any file size; the eager peak
            grows with the file. Exact bytes vary by version, so the cell prints the comparison.
            """
        ),
        code(
            '''
            def traced_peak(thunk: Callable[[], object]) -> tuple[object, int]:
                """Run thunk under tracemalloc; return (result, peak bytes)."""
                tracemalloc.start()
                try:
                    result = thunk()
                    return result, tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()


            streamed_count, streaming_peak = traced_peak(lambda: sum(1 for _ in read_lines(log_path)))
            eager_count, eager_peak = traced_peak(
                lambda: len(log_path.read_text(encoding="utf-8").splitlines())
            )
            print(f"{streamed_count=}, {eager_count=}")
            print(f"streaming peak at least 10x smaller than eager: {streaming_peak * 10 < eager_peak}")
            '''
        ),
    ]


def _parsing_cells() -> list[NotebookNode]:
    """Step 3: parsing with re and match."""
    return [
        md(
            """
            ### Step 3 — Parse with `re` and `match`

            Parsing happens in two stages:

            1. **`re.fullmatch`** checks the *shape* of the line and extracts the fields with
               named groups. Anything that does not have the shape (truncated, garbage) fails
               here.
            2. A **`match`** statement on `(method, status)` applies the *rules* with guards:
               only real HTTP methods, only status codes 100–599.

            Every rejection raises `MalformedLineError`, which carries the line number, the raw
            line and a short `reason`. It derives from a project base class and from
            `ValueError` (the pattern from 1.14.5). Good lines become an `AccessRecord`
            `NamedTuple` (1.5.6).
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            The pattern, piece by piece (adjacent raw strings are joined by the compiler, so each
            field gets its own line):
            """
        ),
        code(
            r'''
            ACCESS_LINE_PATTERN = re.compile(
                r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
                r" (?P<client_ip>\d{1,3}(?:\.\d{1,3}){3})"
                r' "(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/1\.1"'
                r" (?P<status>\d{3})"
                r" (?P<latency_ms>\d+)ms"
            )
            HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


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
            '''
        ),
        md(
            """
            Trying the parser on one line of each kind. The broken lines raise, and the cell
            prints the reason of each `MalformedLineError`:
            """
        ),
        code(
            """
            sample_lines = [
                '2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1" 200 23ms',
                '2026-11-06T09:00:01Z 10.0.1.5 "POST /api/check',
                "<html>502 Bad Gateway</html>",
                '2026-11-06T09:00:02Z 10.0.3.9 "BREW /api/products HTTP/1.1" 200 41ms',
                '2026-11-06T09:00:03Z 10.0.0.4 "GET /health HTTP/1.1" 999 2ms',
            ]
            for sample_number, sample_line in enumerate(sample_lines, start=1):
                try:
                    print(parse_access_line(sample_number, sample_line))
                except MalformedLineError as error:
                    print(f"{type(error).__name__}: {error}")
            """
        ),
    ]


def _collect_cells() -> list[NotebookNode]:
    """Step 4: collect errors without stopping."""
    return [
        md(
            """
            ### Step 4 — Collect `MalformedLineError`s without stopping

            One bad line must not abort the analysis of twenty thousand good ones. `parse_records`
            is a generator stage between `read_lines` and the aggregation: it catches **only**
            `MalformedLineError` (a bug elsewhere still surfaces), appends it to a list the
            caller owns, and moves on. The `yield` sits in the `else` clause, so the `except`
            guards only the parsing call (1.14.2).
            """
        ),
        code(
            '''
            def parse_records(
                numbered_lines: Iterable[tuple[int, str]], malformed: list[MalformedLineError]
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
            sample_records = list(parse_records(enumerate(sample_lines, start=1), sample_malformed))
            print(f"{len(sample_records)} record(s), {len(sample_malformed)} malformed:")
            for error in sample_malformed:
                print(f"  line {error.line_number}: {error.reason:<20} {error.line[:40]!r}")
            '''
        ),
    ]


def _aggregate_cells() -> list[NotebookNode]:
    """Step 5: aggregation."""
    return [
        md(
            """
            ### Step 5 — Aggregate status codes, top endpoints and p95 latency

            Three helpers first:

            - **`normalize_endpoint`** groups `/api/orders/17` and `/api/orders/4012` as one
              endpoint, `GET /api/orders/{id}`: it drops the query string and replaces every
              all-digit path segment with `re.sub`.
            - **`percentile(values, percent)`** uses the *nearest-rank* method: sort, then take
              the value at rank `ceil(percent / 100 * n)`. The p95 latency is the time that 95%
              of requests beat; unlike the mean, it is not hidden by many fast requests.
            - **`status_class`** names a status family with `match` on `status // 100`.
            """
        ),
        code(
            r'''
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
            '''
        ),
        md(
            """
            `aggregate` makes **one pass** over the records, so it works on the lazy pipeline
            directly:

            | Container | Holds |
            | --- | --- |
            | `Counter[int]` | requests per status code |
            | `Counter[str]` | requests per normalized endpoint |
            | `defaultdict(list)` | latencies per endpoint (for the per-endpoint p95) |
            | `list[int]` | every latency (for the overall p95) |

            The latency lists are the only part that grows with the input; a production tool
            would use a streaming quantile sketch instead. `@timer` (1.12.3) records how long the
            pass takes into `timing_lines`, which Step 7 prints.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            `top_endpoints` ranks with `sorted` and a tuple key (count descending, then name
            ascending, the pattern of Lab 1.6's `top_k_words`), so ties come out in a stable,
            documented order rather than in insertion order as `Counter.most_common` would.
            """
        ),
        code(
            '''
            def top_endpoints(summary: AccessSummary, count: int = 5) -> list[tuple[str, int, int]]:
                """(endpoint, requests, p95 ms) for the busiest endpoints."""
                ranked = sorted(summary.endpoint_counts.items(), key=lambda item: (-item[1], item[0]))
                return [
                    (endpoint, requests, percentile(summary.latencies_by_endpoint[endpoint], 95))
                    for endpoint, requests in ranked[:count]
                ]


            sample_summary = aggregate(sample_records)
            print(sample_summary.status_counts, top_endpoints(sample_summary))
            '''
        ),
    ]


def _report_cells() -> list[NotebookNode]:
    """Step 6: report rendering."""
    return [
        md(
            """
            ### Step 6 — Render an aligned report

            Every line of the report is exactly `REPORT_WIDTH` (60) characters, built from format
            specs (1.4.3): `<` / `>` alignment, `,` thousands separators, `.1%` percentages, and
            `-<60` to fill a section rule with dashes. Malformed examples are cut to fit. The
            report is a pure function of its inputs, so it is easy to test (Step 9).
            """
        ),
        code(
            '''
            REPORT_WIDTH = 60


            def fit(text: str) -> str:
                """Cut or pad text to exactly REPORT_WIDTH characters."""
                if len(text) > REPORT_WIDTH:
                    text = text[: REPORT_WIDTH - 1] + "…"
                return f"{text:<{REPORT_WIDTH}}"


            def render_report(summary: AccessSummary, malformed: list[MalformedLineError]) -> str:
                """Build the full text report."""
                total_lines = summary.record_count + len(malformed)
                lines = [
                    "ACCESS LOG REPORT".center(REPORT_WIDTH, "="),
                    f"{'Lines read':<30}{total_lines:>30,}",
                    f"{'Records parsed':<30}{summary.record_count:>30,}",
                    f"{'Malformed lines':<30}{len(malformed):>30,}",
                    f"{'Overall p95 latency (ms)':<30}{percentile(summary.all_latencies, 95):>30,}",
                    f"{'Status codes ':-<{REPORT_WIDTH}}",
                    f"{'Status':<8}{'Class':<22}{'Requests':>15}{'Share':>15}",
                ]
                for status, requests in sorted(summary.status_counts.items()):
                    share = requests / summary.record_count
                    lines.append(f"{status:<8}{status_class(status):<22}{requests:>15,}{share:>15.1%}")
                lines.append(f"{'Top endpoints ':-<{REPORT_WIDTH}}")
                lines.append(f"{'Endpoint':<34}{'Requests':>13}{'p95 ms':>13}")
                for endpoint, requests, p95_ms in top_endpoints(summary):
                    lines.append(f"{endpoint:<34}{requests:>13,}{p95_ms:>13,}")
                lines.append(f"{'Malformed lines by reason ':-<{REPORT_WIDTH}}")
                for reason, reason_count in sorted(Counter(e.reason for e in malformed).items()):
                    lines.append(f"{reason:<34}{reason_count:>26,}")
                for error in malformed[:3]:
                    lines.append(fit(f"  e.g. line {error.line_number}: {error.line!r}"))
                lines.append("=" * REPORT_WIDTH)
                return "\\n".join(lines)


            print(render_report(sample_summary, sample_malformed))
            '''
        ),
    ]


def _run_cells() -> list[NotebookNode]:
    """Steps 7 and 8: the timed run, the upload, strict mode."""
    return [
        md(
            """
            ### Step 7 — Run the analysis, timed with a context manager

            `analyze_access_log` wires the stages together. Nothing is read until `aggregate`
            pulls the first record; the whole file then streams through
            `read_lines → parse_records → aggregate` in a single pass.

            With `strict=True` it still collects **every** malformed line first, then raises them
            together as one `ExceptionGroup` (1.14.6), so a caller sees all problems at once
            instead of only the first. Step 8 handles that with `except*`.
            """
        ),
        code(
            '''
            def analyze_access_log(
                path: Path, *, strict: bool = False
            ) -> tuple[AccessSummary, list[MalformedLineError]]:
                """Stream the log through the pipeline; optionally fail on malformed lines."""
                malformed: list[MalformedLineError] = []
                summary = aggregate(parse_records(read_lines(path), malformed))
                if strict and malformed:
                    raise ExceptionGroup(f"{len(malformed)} malformed lines in {path.name}", malformed)
                return summary, malformed
            '''
        ),
        md(
            """
            The run itself, inside `with Timer(...)`. The two timing lines at the end (the
            `Timer` block and the `@timer` on `aggregate`) vary by machine; the report above them
            is identical on every run.
            """
        ),
        code(
            """
            timing_lines.clear()
            with Timer("full analysis", report=timing_lines.append):
                access_summary, malformed_lines = analyze_access_log(log_path)
                report_text = render_report(access_summary, malformed_lines)

            print(report_text)
            print("\\n".join(timing_lines))
            """
        ),
        md(
            """
            ### Step 8 — Upload with `@retry`, and strict mode with `except*`

            The report goes to a (simulated) report server that drops the first two connections.
            `upload_report` is wrapped in `@retry` (1.12.6), which retries only on
            `ConnectionError` / `TimeoutError` with exponential backoff. `sleep` records the
            delays instead of waiting, as in 1.12.6; in production you would keep the default
            `time.sleep`. The server writes what it receives to `scratch_dir`.
            """
        ),
        code(
            '''
            class FlakyReportServer:
                """Refuses the first `failures` uploads, then stores the report in a file."""

                def __init__(self, failures: int, destination: Path) -> None:
                    self.failures_left = failures
                    self.destination = destination
                    self.attempts = 0

                def receive(self, report: str) -> int:
                    """Store the report and return its size in bytes, or raise ConnectionError."""
                    self.attempts += 1
                    if self.failures_left > 0:
                        self.failures_left -= 1
                        raise ConnectionError(f"connection reset (attempt {self.attempts})")
                    self.destination.write_text(report + "\\n", encoding="utf-8")
                    return self.destination.stat().st_size


            report_server = FlakyReportServer(failures=2, destination=scratch_dir / "phase1_log_report.txt")
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
            '''
        ),
        md(
            """
            **Strict mode.** A pipeline that must not accept bad input runs with `strict=True`.
            The caller handles the whole group with `except* MalformedLineError`: one clause
            receives every malformed line at once. Any *other* exception type in the group would
            not be swallowed here; it would be re-raised.
            """
        ),
        code(
            """
            try:
                analyze_access_log(log_path, strict=True)
            except* MalformedLineError as malformed_group:
                reasons = Counter(error.reason for error in malformed_group.exceptions)
                print(f"strict run rejected: {malformed_group.message}")
                print(f"by reason: {dict(sorted(reasons.items()))}")
                first_problem = malformed_group.exceptions[0]
                print(f"first problem: {first_problem} -> {first_problem.line[:45]!r}")
            """
        ),
    ]


def _self_check_cells() -> list[NotebookNode]:
    """Step 9: self-check."""
    return [
        md(
            """
            ### Step 9 — Self-check

            The project's own tests, with the shared `run_checks`. They tie the output back to the
            input: every line is either a record or a malformed line, the malformed reasons match
            what Step 1 injected (truncated and garbage lines both fail the regex, as
            `"unrecognized format"`), and the report is aligned. All checks should pass.
            """
        ),
        code(
            '''
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
            '''
        ),
        md("Run the checks."),
        code(
            """
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
                    ("percentile", lambda: (percentile(range(1, 101), 95), percentile([5], 95)), (95, 5)),
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
                    ("upload retried twice", lambda: (report_server.attempts, upload_delays), (3, [0.05, 0.1])),
                    (
                        "strict mode raises a group",
                        lambda: raised_error_name(lambda: analyze_access_log(log_path, strict=True)),
                        "ExceptionGroup",
                    ),
                    ("pipeline is lazy", lambda: inspect.isgenerator(parse_records([], [])), True),
                ]
            )
            """
        ),
        md(
            """
            **Extensions to try:** read a `.gz` log with `gzip.open(path, "rt")` (nothing else
            changes, because every stage takes an iterable); add a `--since` time filter as one
            more generator stage; report requests per minute with
            `Counter(record.timestamp[:16] for record in records)`; replace the latency lists
            with a fixed-size reservoir sample to make memory constant.
            """
        ),
    ]


QUESTIONS: list[tuple[str, str, str, str]] = [
    # (unit, snippet, answer, proof); proof is the snippet unless given separately
    (
        "1.1",
        """
        def checkout_total() -> int:
            return subtotal + delivery_fee


        subtotal = 400
        delivery_fee = 40
        print(checkout_total())
        """,
        """
        `440`. Compiling the `def` only creates the function; global names inside it are
        looked up when it **runs** (`LOAD_GLOBAL`), and by then both exist.
        """,
        "",
    ),
    (
        "1.1",
        """
        print(eval("[n * n for n in range(4)]"))
        try:
            eval("total = 5")
        except SyntaxError:
            print("SyntaxError")
        """,
        """
        `[0, 1, 4, 9]`, then `SyntaxError`. `eval` accepts only an **expression**; an
        assignment is a statement (use `exec` for statements, or `:=` for an assignment
        expression).
        """,
        "",
    ),
    (
        "1.2",
        """
        prices = [100, 200]
        alias = prices
        alias += [300]
        alias = alias + [400]
        print(prices, alias)
        """,
        """
        `[100, 200, 300] [100, 200, 300, 400]`. `+=` on a list mutates it in place (both
        names see it); `alias + [400]` builds a **new** list and rebinds only `alias`.
        """,
        "",
    ),
    (
        "1.2",
        """
        def add_item(cart: list[str], item: str) -> None:
            cart.append(item)
            cart = ["reset"]


        basket = ["rice"]
        add_item(basket, "dal")
        print(basket)
        """,
        """
        `['rice', 'dal']`. The parameter is a second name for the caller's list: `append`
        mutates that object, while `cart = [...]` only rebinds the local name (call by object
        reference).
        """,
        "",
    ),
    (
        "1.3",
        """
        print(0.1 + 0.2 == 0.3, round(2.5), round(3.5), -7 // 2, -7 % 2)
        """,
        """
        `False 2 4 -4 1`. Binary floats cannot store 0.1 exactly; `round` rounds halves to
        even (banker's rounding); `//` floors toward minus infinity, and `%` takes the sign of
        the divisor.
        """,
        "",
    ),
    (
        "1.3",
        """
        from decimal import Decimal

        print(True + True, isinstance(True, int), Decimal("0.1") * 3 == Decimal("0.3"), bool("False"))
        """,
        """
        `2 True True True`. `bool` is a subclass of `int` (`True == 1`); `Decimal` built from
        strings is exact; any non-empty string is truthy, including `"False"`.
        """,
        "",
    ),
    (
        "1.4",
        """
        word = "naïve"
        print(len(word), len(word.encode("utf-8")), word[::-1].upper())
        """,
        """
        `5 6 EVÏAN`. `len` counts code points (5); UTF-8 needs two bytes for `ï`, so 6 bytes;
        slicing and `upper` work on code points too. (A decomposed `ï`, `i` plus a combining
        mark, would make the length 6: see 1.4.4.)
        """,
        "",
    ),
    (
        "1.4",
        """
        print("a,b,,c".split(","), "a b  c".split(), "-".join("abc"), repr("Hello"[10:]))
        """,
        """
        `['a', 'b', '', 'c'] ['a', 'b', 'c'] a-b-c ''`. With a separator, `split` keeps empty
        fields; with no argument it splits on runs of whitespace; `join` iterates the string;
        slicing past the end returns `''` instead of raising.
        """,
        "",
    ),
    (
        "1.5",
        """
        grid = [[0] * 2] * 2
        grid[0][0] = 9
        print(grid)
        """,
        """
        `[[9, 0], [9, 0]]`. The outer `* 2` copies the **reference** to one inner list, so
        both rows are the same object. Build rows with `[[0] * 2 for _ in range(2)]`.
        """,
        "",
    ),
    (
        "1.5",
        """
        order = ("tea", ["cup"])
        try:
            order[1] += ["saucer"]
        except TypeError as error:
            print(type(error).__name__)
        print(order)
        """,
        """
        `TypeError`, then `('tea', ['cup', 'saucer'])`. `+=` first extends the list in place
        (that succeeds), then tries to store the result back into the tuple slot (that fails).
        The mutation has already happened.
        """,
        "",
    ),
    (
        "1.5",
        """
        names = ["bea", "Al", "cy", "Bo"]
        print(sorted(names))
        print(sorted(names, key=str.lower))
        print(names.sort())
        """,
        """
        `['Al', 'Bo', 'bea', 'cy']`, `['Al', 'bea', 'Bo', 'cy']`, `None`. Uppercase letters
        sort before lowercase by code point; `key=str.lower` compares case-insensitively;
        `list.sort()` sorts in place and returns `None`.
        """,
        "",
    ),
    (
        "1.6",
        """
        labels = {1: "int", 1.0: "float", True: "bool"}
        print(labels)
        """,
        """
        `{1: 'bool'}`. `1`, `1.0` and `True` are equal and hash the same, so they are one
        key. The **first** key object is kept, the **last** value wins.
        """,
        """
        labels = {1: "int", 1.0: "float", True: "bool"}  # noqa: F601 (the point of the question)
        print(labels)
        """,
    ),
    (
        "1.6",
        """
        prices = {"tea": 10, "coffee": 20}
        prices["tea"] = 15
        prices |= {"juice": 30, "tea": 5}
        print(list(prices), prices["tea"])
        """,
        """
        `['tea', 'coffee', 'juice'] 5`. Dicts keep insertion order; updating an existing key
        (by assignment or `|=`) changes its value but **not** its position.
        """,
        "",
    ),
    (
        "1.6",
        """
        from collections import Counter

        letters = Counter("mississippi")
        print(letters.most_common(2), letters["z"], "z" in letters)
        """,
        """
        `[('i', 4), ('s', 4)] 0 False`. Ties in `most_common` keep first-seen order (`i`
        appears before `s`); a missing key reads as `0` but is **not** inserted.
        """,
        "",
    ),
    (
        "1.7",
        """
        order = {"items": ["pen"], "total": 10}
        snapshot = order.copy()
        snapshot["items"].append("ink")
        snapshot["total"] = 25
        print(order)
        """,
        """
        `{'items': ['pen', 'ink'], 'total': 10}`. A shallow copy is a new dict holding the
        **same** values: the shared list sees the `append`, while rebinding `total` in the
        copy does not touch the original.
        """,
        "",
    ),
    (
        "1.7",
        """
        import copy

        shared = [1]
        pair = [shared, shared]
        clone = copy.deepcopy(pair)
        clone[0].append(2)
        print(clone, clone[0] is clone[1], pair)
        """,
        """
        `[[1, 2], [1, 2]] True [[1], [1]]`. `deepcopy` copies the inner list once and uses its
        `memo` to reuse that copy, so the clone keeps the original's sharing structure while
        sharing nothing with the original.
        """,
        "",
    ),
    (
        "1.8",
        """
        print(0 or [] or "default", 0 and 1 / 0, None or 0, [] and "never")
        """,
        """
        `default 0 0 []`. `or` returns the first truthy operand (or the last one); `and`
        returns the first falsy operand (or the last one) and short-circuits, so `1 / 0` never
        runs.
        """,
        "",
    ),
    (
        "1.8",
        """
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


        print(describe("go"), describe(["go"]), describe(("go", "fast", "now")), describe({}))
        """,
        """
        `text one: go many: go +2 other`. Sequence patterns match lists and tuples but
        deliberately **not** strings, so `"go"` falls through to `str()`; a dict is not a
        sequence at all.
        """,
        "",
    ),
    (
        "1.9",
        """
        squares = (n * n for n in range(4))
        print(sum(squares), sum(squares))
        print(list(zip("ab", [1, 2, 3], strict=False)))
        """,
        """
        `14 0`, then `[('a', 1), ('b', 2)]`. A generator expression is single use, so the
        second `sum` sees nothing; `zip` stops at the shortest input (unless `strict=True`).
        """,
        "",
    ),
    (
        "1.9",
        """
        print(any([]), all([]), max([], default="none"), list(enumerate("xy", start=1)))
        """,
        """
        `False True none [(1, 'x'), (2, 'y')]`. `any` of nothing is `False`, `all` of nothing
        is `True` (no counter-example); `max` of an empty iterable needs `default`.
        """,
        "",
    ),
    (
        "1.10",
        """
        def add_tag(tag: str, tags: list[str] = []) -> list[str]:
            tags.append(tag)
            return tags


        print(add_tag("a"), add_tag("b"))
        """,
        """
        `['a', 'b'] ['a', 'b']`. The default list is created **once**, at `def` time, and
        shared by every call. Both calls return that same list, and `print` shows it after
        both appends.
        """,
        """
        def add_tag(tag: str, tags: list[str] = []) -> list[str]:  # noqa: B006 (the trap)
            tags.append(tag)
            return tags


        print(add_tag("a"), add_tag("b"))
        """,
    ),
    (
        "1.10",
        """
        def book_room(room_number: int, /, guest: str, *, nights: int = 1) -> str:
            return f"{room_number}:{guest}:{nights}"


        print(book_room(101, guest="Asha", nights=2))
        print(book_room(102, "Ravi"))
        try:
            book_room(room_number=103, guest="Meena")
        except TypeError:
            print("TypeError")
        """,
        """
        `101:Asha:2`, `102:Ravi:1`, `TypeError`. Parameters before `/` are positional-only, so
        `room_number=` is rejected; `guest` can be passed either way; `nights` (after `*`) only
        by keyword.
        """,
        "",
    ),
    (
        "1.11",
        """
        multipliers = [lambda x: x * factor for factor in range(3)]
        print([multiply(10) for multiply in multipliers])
        """,
        """
        `[20, 20, 20]`. Each lambda closes over the **variable** `factor`, not its value at
        creation; when they run, the loop has finished with `factor == 2` (late binding). Fix
        with a default: `lambda x, factor=factor: x * factor`.
        """,
        """
        multipliers = [lambda x: x * factor for factor in range(3)]  # noqa: B023 (late binding)
        print([multiply(10) for multiply in multipliers])
        """,
    ),
    (
        "1.11",
        """
        visits = 0


        def record_visit() -> None:
            visits += 1


        try:
            record_visit()
        except UnboundLocalError:
            print("UnboundLocalError")
        print(visits)
        """,
        """
        `UnboundLocalError`, then `0`. Assigning to `visits` anywhere in the function makes it
        **local** for the whole body (decided at compile time), so `visits += 1` reads a local
        that has no value yet. `global visits` (or better, a parameter) fixes it.
        """,
        '''
        visits = 0


        def record_visit() -> None:
            """Increment the visit counter (broken on purpose)."""
            visits += 1  # noqa: F823, F841 (the trap)


        try:
            record_visit()
        except UnboundLocalError:
            print("UnboundLocalError")
        print(visits)
        ''',
    ),
    (
        "1.12",
        """
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
        """,
        """
        `<b><i>hi</i></b> wrapper`. Decorators apply bottom-up (`tag("b")(tag("i")(greet))`),
        so the outer tag wraps the inner one. Without `functools.wraps`, the result keeps the
        wrapper's name.
        """,
        '''
        def tag(label: str) -> Callable[[Callable[[], str]], Callable[[], str]]:
            """Wrap a function's result in an HTML tag."""

            def decorator(func: Callable[[], str]) -> Callable[[], str]:
                def wrapper() -> str:
                    return f"<{label}>{func()}</{label}>"

                return wrapper

            return decorator


        @tag("b")
        @tag("i")
        def greet() -> str:
            """Say hi."""
            return "hi"


        print(greet(), greet.__name__)
        ''',
    ),
    (
        "1.12",
        """
        import functools


        @functools.lru_cache(maxsize=128)
        def fib(n: int) -> int:
            return n if n < 2 else fib(n - 1) + fib(n - 2)


        print(fib(10), fib.cache_info())
        """,
        """
        `55 CacheInfo(hits=8, misses=11, maxsize=128, currsize=11)`. Each of `fib(0)` …
        `fib(10)` is computed once (11 misses); for `n` from 3 to 10, the `fib(n - 2)` call
        finds the value its sibling branch just cached (8 hits).
        """,
        "",
    ),
    (
        "1.13",
        """
        def countdown(start: int):
            print("starting")
            while start > 0:
                yield start
                start -= 1


        launch = countdown(2)
        print("created")
        print(list(launch), list(launch))
        """,
        """
        `created`, then `starting`, then `[2, 1] []`. Calling a generator function runs none
        of its body; the first `next()` (inside `list`) starts it. A generator is single use,
        so the second `list` is empty.
        """,
        '''
        def countdown(start: int) -> Iterator[int]:
            """Yield start, start - 1, ..., 1."""
            print("starting")
            while start > 0:
                yield start
                start -= 1


        launch = countdown(2)
        print("created")
        print(list(launch), list(launch))
        ''',
    ),
    (
        "1.13",
        """
        import itertools

        print([(key, len(list(group))) for key, group in itertools.groupby("aabaa")])
        print(list(itertools.islice(itertools.count(10, 5), 3)))
        """,
        """
        `[('a', 2), ('b', 1), ('a', 2)]`, then `[10, 15, 20]`. `groupby` groups **consecutive**
        equal items only (sort first to group globally); `islice` takes a finite slice of an
        infinite `count`.
        """,
        "",
    ),
    (
        "1.14",
        """
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
        """,
        """
        `try`, `finally`, `from try`. `else` runs only when the `try` body finishes
        **without** an exception **and** without leaving through `return`/`break`/`continue`;
        `finally` runs on the way out, before the caller receives the value.
        """,
        '''
        def checkout() -> str:
            """Return from try; else is skipped, finally runs."""
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
        ''',
    ),
    (
        "1.14",
        """
        try:
            try:
                {}["sku"]
            except KeyError:
                raise ValueError("bad order") from None
        except ValueError as outer:
            print(repr(outer.__cause__), repr(outer.__context__), outer.__suppress_context__)
        """,
        """
        `None KeyError('sku') True`. `from None` sets no cause and only **hides** the context:
        `__context__` still holds the `KeyError`, and `__suppress_context__` tells the
        traceback printer not to show it.
        """,
        "",
    ),
]


def _question_cells() -> list[NotebookNode]:
    """The 30 predict-the-output questions covering Phase 1."""
    unit_counts: dict[str, int] = {}
    for unit, *_ in QUESTIONS:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    coverage_rows = "\n".join(
        f"            | {unit} | {count} |" for unit, count in unit_counts.items()
    )
    cells = [
        md(
            f"""
            ### Phase 1 review — 30 predict-the-output questions

            Thirty short snippets, at least two from every unit of the phase. For each one,
            decide what it prints **before** opening the answer, then run the proof cell. If a
            question surprises you, go back to the unit it names.

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
    """Phase 1 closing."""
    return [
        md(
            """
            ### Phase 1 complete

            You can now explain any core Python snippet in terms of objects, names, types and
            frames, and you have used every built-in type, the `collections` and `itertools`
            toolkits, functions, closures, decorators, generators, exceptions and context
            managers, together, in one working tool.

            **Next: Phase 2 — Object-Oriented Programming and the Data Model.** Classes,
            dataclasses and the dunder methods behind `len()`, `in`, `with` and iteration, so the
            built-in behaviour you predicted here becomes behaviour you can give your own types.
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for the Phase 1 Project and the closing review."""
    return [
        *_overview_cells(),
        *_generate_cells(),
        *_reading_cells(),
        *_parsing_cells(),
        *_collect_cells(),
        *_aggregate_cells(),
        *_report_cells(),
        *_run_cells(),
        *_self_check_cells(),
        *_question_cells(),
        *_closing_cells(),
    ]
