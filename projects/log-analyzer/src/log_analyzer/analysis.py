"""One-pass aggregation: status codes, endpoints and latency percentiles."""

import logging
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from log_analyzer.models import AccessRecord, AccessSummary, MalformedLineError
from log_analyzer.parsing import parse_records, read_lines

logger = logging.getLogger(__name__)

ID_SEGMENT = re.compile(r"/\d+(?=/|$)")


def normalize_endpoint(method: str, path: str) -> str:
    """``'GET', '/api/orders/42?x=1'`` -> ``'GET /api/orders/{id}'``."""
    route = ID_SEGMENT.sub("/{id}", path.partition("?")[0])
    return f"{method} {route}"


def percentile(values: Iterable[int], percent: float) -> int:
    """Nearest-rank percentile; ``ValueError`` for no values."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of no values")
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def status_class(status: int) -> str:
    """Name the status family of an HTTP status code."""
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


def top_endpoints(summary: AccessSummary, count: int = 5) -> list[tuple[str, int, int]]:
    """``(endpoint, requests, p95 ms)`` for the busiest endpoints; ties broken by name."""
    ranked = sorted(summary.endpoint_counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        (endpoint, requests, percentile(summary.latencies_by_endpoint[endpoint], 95))
        for endpoint, requests in ranked[:count]
    ]


def analyze_access_log(
    path: Path, *, strict: bool = False
) -> tuple[AccessSummary, list[MalformedLineError]]:
    """Stream the log through ``read_lines -> parse_records -> aggregate``.

    Args:
        path: Plain-text or gzip-compressed access log.
        strict: If true, raise every malformed line together as one ``ExceptionGroup``.

    Returns:
        The summary and the list of malformed lines.
    """
    malformed: list[MalformedLineError] = []
    started = time.perf_counter()
    summary = aggregate(parse_records(read_lines(path), malformed))
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "analyzed %s: %d records, %d malformed in %.1f ms",
        path.name,
        summary.record_count,
        len(malformed),
        elapsed_ms,
    )
    if malformed:
        total_lines = summary.record_count + len(malformed)
        logger.warning(
            "%d of %d lines in %s are malformed (%.1f%%)",
            len(malformed),
            total_lines,
            path.name,
            100 * len(malformed) / total_lines,
        )
    if strict and malformed:
        raise ExceptionGroup(f"{len(malformed)} malformed lines in {path.name}", malformed)
    return summary, malformed
