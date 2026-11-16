"""Benchmark every optimization step of the sales report: wall time and peak memory.

Each step runs in **its own child process**, so its peak memory is not hidden by an earlier
step's allocations and one step's warm caches cannot help the next. The child measures:

- **time**: ``time.perf_counter()`` around ``build_report(rows, seed)`` (generation, network
  waits, aggregation and rendering; interpreter start-up and imports excluded);
- **peak memory**: the process's peak resident set size (``ru_maxrss``) when the step ends,
  which includes the interpreter and NumPy (the "imports only" row shows that floor);
- **digest**: SHA-256 of the report text, which must be identical for every step.

Usage (from this folder)::

    python benchmark.py                          # 1,000,000 rows -> RESULTS.md
    python benchmark.py --rows 50000 --output -  # quick run, table on stdout only
    python benchmark.py --repeat 3               # best of 3 runs per step

Timings vary by machine and load; the table records what this machine measured.
"""

import argparse
import hashlib
import json
import os
import platform
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
    """Best-of-N result for one step."""

    step: int
    seconds: float
    peak_bytes: int | None
    digest: str


def measure(step_number: int, rows: int, seed: int, repeat: int) -> Measurement:
    """Run one step in `repeat` fresh child processes; keep the fastest run."""
    runs = []
    for _ in range(repeat):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", str(step_number),
             "--rows", str(rows), "--seed", str(seed)],
            capture_output=True, text=True, check=True, cwd=PROJECT_DIR,
        )  # fmt: skip
        runs.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    best = min(runs, key=lambda run: run["seconds"])
    peaks = [run["peak_bytes"] for run in runs if run["peak_bytes"] is not None]
    return Measurement(step_number, best["seconds"], max(peaks) if peaks else None, best["digest"])


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
        f"- Rows: **{rows:,}**, seed {seed}, best of {repeat} run(s) per step, "
        f"each step in a fresh process; measured {date.today().isoformat()}",
        f"- Python {platform.python_version()} ({build} build), NumPy {numpy.__version__}, "
        f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs",
        f"- Simulated store API: 40 calls x {network_delay:.3f} s each",
        "- Peak memory is the process's peak RSS; Python + NumPy imports alone: "
        f"{mib(floor.peak_bytes)}",
        "",
        "| Step | Change | Time | Peak memory | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for measurement in measurements:
        step = fast_report.STEPS[measurement.step]
        time_cell = f"{measurement.seconds:,.3f} s"
        memory_cell = mib(measurement.peak_bytes)
        if measurement is not baseline:
            time_cell += f" ({baseline.seconds / measurement.seconds:,.1f}x faster)"
            if measurement.peak_bytes and baseline.peak_bytes:
                memory_cell += f" ({baseline.peak_bytes / measurement.peak_bytes:,.1f}x less)"
        lines.append(
            f"| {step.number} | {step.change} | {time_cell} | {memory_cell} | {step.reason} |"
        )
    speedup = baseline.seconds / final.seconds
    memory_ratio = (baseline.peak_bytes or 0) / (final.peak_bytes or 1)
    met = speedup >= TARGET_SPEEDUP and memory_ratio >= TARGET_MEMORY_RATIO
    identical = len({m.digest for m in measurements}) == 1
    lines += [
        "",
        f"**Result: {speedup:,.1f}x faster and {memory_ratio:,.1f}x less peak memory** "
        f"(step 0 -> step {final.step}); target >= {TARGET_SPEEDUP:g}x faster and "
        f">= {TARGET_MEMORY_RATIO:g}x less memory: {'met' if met else 'NOT met'}.",
        "",
        f"Reports identical across all steps: {'yes' if identical else 'NO'} "
        f"(SHA-256 `{final.digest[:16]}...`).",
    ]
    return "\n".join(lines) + "\n"


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
    return 0 if len({m.digest for m in measurements}) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
