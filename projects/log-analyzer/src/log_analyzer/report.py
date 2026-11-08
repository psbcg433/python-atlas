"""Render a summary as an aligned text report or as a JSON-ready document."""

from collections import Counter
from typing import TypedDict

from log_analyzer.analysis import percentile, status_class, top_endpoints
from log_analyzer.models import AccessSummary, MalformedLineError

REPORT_WIDTH = 60


class EndpointStats(TypedDict):
    """One row of the top-endpoints table."""

    endpoint: str
    requests: int
    p95_ms: int


class SummaryDocument(TypedDict):
    """The report as data (what ``report --format json`` prints)."""

    lines_read: int
    records_parsed: int
    malformed_lines: int
    p95_latency_ms: int | None
    status_counts: dict[str, int]
    top_endpoints: list[EndpointStats]
    malformed_by_reason: dict[str, int]


def shorten(text: str, width: int) -> str:
    """Cut text to at most ``width`` characters, marking a cut with an ellipsis."""
    return text if len(text) <= width else text[: width - 1] + "…"


def fit(text: str) -> str:
    """Cut or pad text to exactly ``REPORT_WIDTH`` characters."""
    return f"{shorten(text, REPORT_WIDTH):<{REPORT_WIDTH}}"


def _reason_counts(malformed: list[MalformedLineError]) -> list[tuple[str, int]]:
    """Malformed-line counts per reason, sorted by reason."""
    return sorted(Counter(error.reason for error in malformed).items())


def render_report(
    summary: AccessSummary, malformed: list[MalformedLineError], *, top: int = 5
) -> str:
    """Build the text report; every line is exactly ``REPORT_WIDTH`` characters."""
    total_lines = summary.record_count + len(malformed)
    overall_p95 = f"{percentile(summary.all_latencies, 95):,}" if summary.record_count else "-"
    lines = [
        "ACCESS LOG REPORT".center(REPORT_WIDTH, "="),
        f"{'Lines read':<30}{total_lines:>30,}",
        f"{'Records parsed':<30}{summary.record_count:>30,}",
        f"{'Malformed lines':<30}{len(malformed):>30,}",
        f"{'Overall p95 latency (ms)':<30}{overall_p95:>30}",
        f"{'Status codes ':-<{REPORT_WIDTH}}",
        f"{'Status':<8}{'Class':<22}{'Requests':>15}{'Share':>15}",
    ]
    for status, requests in sorted(summary.status_counts.items()):
        share = requests / summary.record_count
        lines.append(f"{status:<8}{status_class(status):<22}{requests:>15,}{share:>15.1%}")
    lines.append(f"{'Top endpoints ':-<{REPORT_WIDTH}}")
    lines.append(f"{'Endpoint':<34}{'Requests':>13}{'p95 ms':>13}")
    for endpoint, requests, p95_ms in top_endpoints(summary, top):
        lines.append(f"{shorten(endpoint, 33):<34}{requests:>13,}{p95_ms:>13,}")
    lines.append(f"{'Malformed lines by reason ':-<{REPORT_WIDTH}}")
    for reason, reason_count in _reason_counts(malformed):
        lines.append(f"{reason:<34}{reason_count:>26,}")
    for error in malformed[:3]:
        lines.append(fit(f"  e.g. line {error.line_number}: {error.line!r}"))
    lines.append("=" * REPORT_WIDTH)
    return "\n".join(lines)


def summary_document(
    summary: AccessSummary, malformed: list[MalformedLineError], *, top: int = 5
) -> SummaryDocument:
    """The same facts as ``render_report``, as a JSON-serializable dict."""
    return {
        "lines_read": summary.record_count + len(malformed),
        "records_parsed": summary.record_count,
        "malformed_lines": len(malformed),
        "p95_latency_ms": percentile(summary.all_latencies, 95) if summary.record_count else None,
        "status_counts": {
            str(status): requests for status, requests in sorted(summary.status_counts.items())
        },
        "top_endpoints": [
            {"endpoint": endpoint, "requests": requests, "p95_ms": p95_ms}
            for endpoint, requests, p95_ms in top_endpoints(summary, top)
        ],
        "malformed_by_reason": dict(_reason_counts(malformed)),
    }
