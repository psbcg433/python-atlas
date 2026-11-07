"""Memory profiling: run a callable under tracemalloc and report its top allocating lines."""

import linecache
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Frames from these files are tracemalloc's (or this module's) own bookkeeping.
_IGNORED_FILES = (tracemalloc.__file__, __file__, "<frozen importlib._bootstrap*>")


@dataclass(frozen=True, slots=True)
class AllocationSite:
    """Memory still held after the call, grouped by the source line that allocated it."""

    filename: str
    lineno: int
    source: str
    size_bytes: int
    blocks: int

    @property
    def location(self) -> str:
        """``file.py:line`` (file name only, never the full path)."""
        return f"{Path(self.filename).name}:{self.lineno}"


@dataclass(frozen=True, slots=True)
class MemoryReport:
    """What profile_allocations measured for one call."""

    function_name: str
    result: object
    peak_bytes: int
    retained_bytes: int
    sites: tuple[AllocationSite, ...]


def profile_allocations(
    function: Callable[..., object],
    /,
    *args: object,
    top: int = 10,
    min_bytes: int = 1024,
    **kwargs: object,
) -> MemoryReport:
    """Call ``function(*args, **kwargs)`` under tracemalloc.

    ``peak_bytes`` is the highest extra memory during the call (temporaries included);
    ``retained_bytes`` and ``sites`` describe memory still held when it returned, including
    its return value. Lines holding less than ``min_bytes`` are left out (allocator and
    regex-cache noise). Tracing is left as it was found.
    """
    if top < 1:
        raise ValueError("top must be at least 1")
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    ignore = [tracemalloc.Filter(False, pattern) for pattern in _IGNORED_FILES]
    try:
        tracemalloc.take_snapshot().filter_traces(ignore)  # warm-up: compiles the filter patterns
        before = tracemalloc.take_snapshot().filter_traces(ignore)
        tracemalloc.reset_peak()
        baseline_bytes, _ = tracemalloc.get_traced_memory()
        result = function(*args, **kwargs)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        after = tracemalloc.take_snapshot().filter_traces(ignore)
    finally:
        if started_here:
            tracemalloc.stop()
    growth = [stat for stat in after.compare_to(before, "lineno") if stat.size_diff >= min_bytes]
    sites = tuple(
        AllocationSite(
            filename=stat.traceback[0].filename,
            lineno=stat.traceback[0].lineno,
            source=linecache.getline(stat.traceback[0].filename, stat.traceback[0].lineno).strip(),
            size_bytes=stat.size_diff,
            blocks=stat.count_diff,
        )
        for stat in growth[:top]
    )
    return MemoryReport(
        function_name=getattr(function, "__qualname__", repr(function)),
        result=result,
        peak_bytes=max(peak_bytes - baseline_bytes, 0),
        retained_bytes=max(current_bytes - baseline_bytes, 0),
        sites=sites,
    )


def format_bytes(size_bytes: int) -> str:
    """Human-readable size: B, KiB or MiB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes / (1024 * 1024):.1f} MiB"


def format_memory_report(report: MemoryReport) -> str:
    """Render a MemoryReport as text."""
    lines = [
        f"memory report for {report.function_name}",
        f"  peak during the call:   {format_bytes(report.peak_bytes)}",
        f"  held after the call:    {format_bytes(report.retained_bytes)}",
        "  top allocating lines (memory still held):",
    ]
    if not report.sites:
        lines.append("    (nothing retained)")
    for site in report.sites:
        lines.append(
            f"    {format_bytes(site.size_bytes):>10}  {site.blocks:>8,} blocks  "
            f"{site.location:<18} {site.source}"
        )
    return "\n".join(lines)
