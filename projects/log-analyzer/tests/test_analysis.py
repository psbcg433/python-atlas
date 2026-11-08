"""Aggregation helpers and the full analysis pipeline."""

import logging
from collections import Counter
from pathlib import Path

import pytest

from log_analyzer.analysis import (
    aggregate,
    analyze_access_log,
    normalize_endpoint,
    percentile,
    status_class,
    top_endpoints,
)
from log_analyzer.models import AccessRecord, MalformedLineError


def record(method: str, path: str, status: int = 200, latency_ms: int = 10) -> AccessRecord:
    """A record with fixed timestamp and client."""
    return AccessRecord("2026-11-06T09:00:00Z", "10.0.0.1", method, path, status, latency_ms)


@pytest.mark.parametrize(
    ("method", "path", "endpoint"),
    [
        ("GET", "/api/orders/42?expand=items", "GET /api/orders/{id}"),
        ("PUT", "/api/users/7/address", "PUT /api/users/{id}/address"),
        ("GET", "/api/v2/products", "GET /api/v2/products"),
        ("GET", "/health", "GET /health"),
        ("DELETE", "/api/cart/items/12?force=1", "DELETE /api/cart/items/{id}"),
    ],
)
def test_normalize_endpoint(method: str, path: str, endpoint: str) -> None:
    assert normalize_endpoint(method, path) == endpoint


def test_percentile_nearest_rank() -> None:
    assert percentile(range(1, 101), 95) == 95
    assert percentile([120, 15, 30], 50) == 30
    assert percentile([5], 95) == 5
    assert percentile([3, 1, 2], 0) == 1


def test_percentile_of_nothing() -> None:
    with pytest.raises(ValueError, match="no values"):
        percentile([], 95)


@pytest.mark.parametrize(
    ("status", "family"),
    [
        (101, "informational"),
        (204, "success"),
        (304, "redirect"),
        (404, "client error"),
        (503, "server error"),
    ],
)
def test_status_class(status: int, family: str) -> None:
    assert status_class(status) == family


def test_aggregate_counts_in_one_pass() -> None:
    records = [
        record("GET", "/api/orders/1", latency_ms=10),
        record("GET", "/api/orders/2", status=404, latency_ms=30),
        record("GET", "/health", latency_ms=1),
    ]
    summary = aggregate(iter(records))  # a one-shot iterator is enough
    assert summary.record_count == 3
    assert summary.status_counts == Counter({200: 2, 404: 1})
    assert summary.endpoint_counts == Counter({"GET /api/orders/{id}": 2, "GET /health": 1})
    assert summary.latencies_by_endpoint["GET /api/orders/{id}"] == [10, 30]
    assert summary.all_latencies == [10, 30, 1]


def test_top_endpoints_breaks_ties_by_name() -> None:
    summary = aggregate(
        [record("GET", "/b"), record("GET", "/a"), record("GET", "/c", latency_ms=99)] * 2
        + [record("GET", "/c")]
    )
    assert top_endpoints(summary, 2) == [("GET /c", 3, 99), ("GET /a", 2, 10)]


def test_analyze_returns_summary_and_malformed(sample_log: Path) -> None:
    summary, malformed = analyze_access_log(sample_log)
    assert summary.record_count == 2
    assert [error.reason for error in malformed] == [
        "unrecognized format",
        "unrecognized format",
        "unknown method",
        "status out of range",
    ]


def test_analyze_logs_counts_and_a_warning(
    sample_log: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="log_analyzer"):
        analyze_access_log(sample_log)
    messages = [(record.levelname, record.getMessage()) for record in caplog.records]
    assert messages[0][0] == "INFO"
    assert messages[0][1].startswith("analyzed sample.log: 2 records, 4 malformed in ")
    assert messages[1] == ("WARNING", "4 of 6 lines in sample.log are malformed (66.7%)")


def test_analyze_clean_log_does_not_warn(clean_log: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="log_analyzer"):
        summary, malformed = analyze_access_log(clean_log, strict=True)
    assert (summary.record_count, malformed, caplog.records) == (200, [], [])


def test_strict_mode_raises_every_malformed_line_at_once(sample_log: Path) -> None:
    with pytest.raises(ExceptionGroup) as caught:
        analyze_access_log(sample_log, strict=True)
    group = caught.value
    assert group.message == "4 malformed lines in sample.log"
    assert all(isinstance(error, MalformedLineError) for error in group.exceptions)
    assert len(group.exceptions) == 4
