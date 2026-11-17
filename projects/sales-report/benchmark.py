"""Benchmark every optimization step of the sales report: wall time and peak memory.

Each step runs in **its own child process**, so its peak memory is not hidden by an earlier
step's allocations and one step's warm caches cannot help the next. The child measures:

- **time**: ``time.perf_counter()`` around ``build_report(rows, seed)`` (generation, network
  waits, aggregation and rendering; interpreter start-up and imports excluded). With
  ``--repeat N`` every step runs N times; the table shows the best and the median run;
- **peak memory**: the process's peak resident set size (``ru_maxrss``) when the step ends,
  which includes the interpreter and NumPy (the "imports only" row shows that floor);
- **digest**: SHA-256 of the report text, which must be identical for every step.

Usage (from this folder)::

    python benchmark.py                          # 1,000,000 rows -> RESULTS.md
    python benchmark.py --rows 50000 --output -  # quick run, table on stdout only
    python benchmark.py --repeat 3               # best and median of 3 runs per step

Timings vary by machine and load; the table records what this machine measured.
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_DIR / "RESULTS.md"
TARGET_SPEEDUP, TARGET_MEMORY_RATIO = 10.0, 3.0
IMPORTS_ONLY = -1  # pseudo-step: import everything, build nothing


def peak_rss_bytes() -> int | None:
    """Peak resident set size of this process, or None where it cannot be read."""
    try:
        import resource
    except ImportError:  # Windows
        try:
            import psutil
        except ImportError:
            return None
        return int(psutil.Process().memory_info().peak_wset)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # Linux reports KiB


def run_step_here(step_number: int, rows: int, seed: int) -> dict[str, object]:
    """Child-process side: run one step and return its measurements."""
    sys.path.insert(0, str(PROJECT_DIR))
    import fast_report

    if step_number == IMPORTS_ONLY:
        return {"seconds": 0.0, "peak_bytes": peak_rss_bytes(), "digest": ""}
    start = time.perf_counter()
    report = fast_report.STEPS[step_number].build(rows, seed)
    seconds = time.perf_counter() - start
    digest = hashlib.sha256(report.encode()).hexdigest()
    return {"seconds": seconds, "peak_bytes": peak_rss_bytes(), "digest": digest}


@dataclass(frozen=True, slots=True)
class Measurement:
    """Timings of one step over N fresh processes, its peak memory and its report digest."""

    step: int
    seconds: float  # the best (fastest) run
    median_seconds: float
    all_seconds: tuple[float, ...]
    peak_bytes: int | None
    digest: str

    @property
    def spread(self) -> float:
        """(slowest - fastest) / median: 0 for a single run."""
        return (max(self.all_seconds) - min(self.all_seconds)) / self.median_seconds


def measure(step_number: int, rows: int, seed: int, repeat: int) -> Measurement:
    """Run one step in `repeat` fresh child processes; keep every time and the highest peak."""
    runs = []
    for _ in range(repeat):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", str(step_number),
             "--rows", str(rows), "--seed", str(seed)],
            capture_output=True, text=True, check=True, cwd=PROJECT_DIR,
        )  # fmt: skip
        runs.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    times = tuple(sorted(run["seconds"] for run in runs))
    peaks = [run["peak_bytes"] for run in runs if run["peak_bytes"] is not None]
    digests = {run["digest"] for run in runs}
    return Measurement(
        step=step_number,
        seconds=times[0],
        median_seconds=statistics.median(times),
        all_seconds=times,
        peak_bytes=max(peaks) if peaks else None,
        digest=digests.pop() if len(digests) == 1 else "differs-between-runs",
    )


def mib(byte_count: int | None) -> str:
    """Bytes -> 'NNN.N MiB' (or 'n/a')."""
    return "n/a" if byte_count is None else f"{byte_count / 2**20:,.1f} MiB"


def render_results(
    measurements: list[Measurement], floor: Measurement, rows: int, seed: int, repeat: int
) -> str:
    """Markdown report: machine facts, the step table, the verdict."""
    import numpy

    import fast_report

    build = "free-threaded" if sysconfig.get_config_var("Py_GIL_DISABLED") else "default (GIL)"
    baseline, final = measurements[0], measurements[-1]
    network_delay = float(os.environ.get("SALES_NETWORK_DELAY", "0.05"))
    lines = [
        "# Sales report benchmark",
        "",
        f"- Rows: **{rows:,}**, seed {seed}, {repeat} run(s) per step (best and median shown), "
        f"each run in a fresh process; measured {date.today().isoformat()}",
        f"- Python {platform.python_version()} ({build} build), NumPy {numpy.__version__}, "
        f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs",
        f"- Simulated store API: 40 calls x {network_delay:.3f} s each",
        "- Peak memory is the highest peak RSS of the runs; Python + NumPy imports alone: "
        f"{mib(floor.peak_bytes)}",
        "",
        "| Step | Change | Time (best) | Time (median) | Peak memory | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for measurement in measurements:
        step = fast_report.STEPS[measurement.step]
        best_cell = f"{measurement.seconds:,.3f} s"
        median_cell = f"{measurement.median_seconds:,.3f} s"
        memory_cell = mib(measurement.peak_bytes)
        if measurement is not baseline:
            best_cell += f" ({baseline.seconds / measurement.seconds:,.1f}x faster)"
            median_cell += f" ({baseline.median_seconds / measurement.median_seconds:,.1f}x faster)"
            if measurement.peak_bytes and baseline.peak_bytes:
                memory_cell += f" ({baseline.peak_bytes / measurement.peak_bytes:,.1f}x less)"
        lines.append(
            f"| {step.number} | {step.change} | {best_cell} | {median_cell} | {memory_cell} "
            f"| {step.reason} |"
        )
    speedup = baseline.seconds / final.seconds
    median_speedup = baseline.median_seconds / final.median_seconds
    memory_ratio = (baseline.peak_bytes or 0) / (final.peak_bytes or 1)
    met = speedup >= TARGET_SPEEDUP and memory_ratio >= TARGET_MEMORY_RATIO
    identical = len({measurement.digest for measurement in measurements}) == 1
    lines += [
        "",
        f"**Result: {speedup:,.1f}x faster and {memory_ratio:,.1f}x less peak memory** "
        f"(best runs, step 0 -> step {final.step}; {median_speedup:,.1f}x faster by median); "
        f"target >= {TARGET_SPEEDUP:g}x faster and >= {TARGET_MEMORY_RATIO:g}x less memory: "
        f"{'met' if met else 'NOT met'}.",
        "",
        f"Reports identical across all steps and runs: {'yes' if identical else 'NO'} "
        f"(SHA-256 `{final.digest[:16]}...`).",
        "",
        *variation_notes(measurements, repeat),
    ]
    return "\n".join(lines) + "\n"


def variation_notes(measurements: list[Measurement], repeat: int) -> list[str]:
    """Markdown notes on run-to-run variation and on the loose timing test."""
    if repeat > 1:
        spreads = ", ".join(
            f"step {measurement.step} {measurement.spread:.0%}" for measurement in measurements
        )
        measured = f"Spread of the {repeat} runs, (slowest - fastest) / median: {spreads}."
    else:
        measured = "One run per step, so no spread was measured (use `--repeat 3`)."
    return [
        f"**Run-to-run variation.** {measured}",
        "",
        "Wall times move with CPU frequency scaling, other load and cache state. The relative",
        "spread is largest for the shortest steps, where a few milliseconds of noise are a big",
        "share, and separate sessions on the same machine can differ by tens of percent for",
        "every step, the baseline included. The best run is the least disturbed one and the",
        "median a typical one; the targets are judged on the best runs, with the median ratio",
        "printed next to them. Read the speedup as an order of magnitude.",
        "",
        "`tests/test_reports.py::test_store_lookups_overlap` asserts that the final version with",
        "40 simulated 50 ms store calls finishes in under 0.5 s, against 2 s if the calls ran",
        "one after another. The threshold is deliberately loose: the overlapped calls take",
        "about 50 ms, so only a regression to sequential calls (or a badly overloaded machine)",
        "can fail it.",
    ]


def main(argv: list[str] | None = None) -> int:
    """Benchmark every step (or, with --child, run one step and print JSON)."""
    parser = argparse.ArgumentParser(description="Benchmark the sales report steps")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT), help="markdown file, or - for stdout only"
    )
    parser.add_argument("--child", type=int, default=None, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.child is not None:
        print(json.dumps(run_step_here(arguments.child, arguments.rows, arguments.seed)))
        return 0
    sys.path.insert(0, str(PROJECT_DIR))
    import fast_report

    floor = measure(IMPORTS_ONLY, 0, arguments.seed, 1)
    measurements = []
    for step in fast_report.STEPS:
        measurement = measure(step.number, arguments.rows, arguments.seed, arguments.repeat)
        print(
            f"step {step.number}: {measurement.seconds:8.3f} s  {mib(measurement.peak_bytes):>12}",
            file=sys.stderr,
        )
        measurements.append(measurement)
    results = render_results(measurements, floor, arguments.rows, arguments.seed, arguments.repeat)
    print(results, end="")
    if arguments.output != "-":
        Path(arguments.output).write_text(results, encoding="utf-8")
        print(f"wrote {arguments.output}", file=sys.stderr)
    return 0 if len({measurement.digest for measurement in measurements}) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
