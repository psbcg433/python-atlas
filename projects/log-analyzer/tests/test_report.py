"""The text report and the JSON summary document."""

import json
from pathlib import Path

from log_analyzer.analysis import aggregate, analyze_access_log
from log_analyzer.generate import write_synthetic_log
from log_analyzer.models import AccessRecord
from log_analyzer.report import REPORT_WIDTH, fit, render_report, shorten, summary_document

DATA_DIR = Path(__file__).parent / "data"


def test_fit_pads_and_cuts() -> None:
    assert fit("abc") == "abc" + " " * (REPORT_WIDTH - 3)
    cut = fit("x" * 100)
    assert len(cut) == REPORT_WIDTH
    assert cut.endswith("…")


def test_shorten() -> None:
    assert shorten("abcdef", 6) == "abcdef"
    assert shorten("abcdefg", 6) == "abcde…"


def test_report_lines_are_aligned(sample_log: Path) -> None:
    report = render_report(*analyze_access_log(sample_log))
    assert {len(line) for line in report.splitlines()} == {REPORT_WIDTH}
    assert "status out of range" in report
    assert "e.g. line 2:" in report


def test_long_endpoint_is_shortened_in_its_column() -> None:
    long_path = "/api/" + "very-long-segment/" * 4
    summary = aggregate(
        [AccessRecord("2026-11-06T09:00:00Z", "10.0.0.1", "GET", long_path, 200, 5)]
    )
    report = render_report(summary, [])
    endpoint_row = next(line for line in report.splitlines() if line.startswith("GET /api/"))
    assert len(endpoint_row) == REPORT_WIDTH
    assert endpoint_row.rstrip().endswith("1            5")


def test_report_for_empty_log(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    summary, malformed = analyze_access_log(empty)
    report = render_report(summary, malformed)
    assert {len(line) for line in report.splitlines()} == {REPORT_WIDTH}
    assert f"{'Overall p95 latency (ms)':<30}{'-':>30}" in report.splitlines()
    assert summary_document(summary, malformed)["p95_latency_ms"] is None


def test_report_matches_the_phase1_notebook(tmp_path: Path) -> None:
    """A 20 000-line seed-42 log gives exactly the report the Phase 1 notebook printed."""
    log_path = tmp_path / "phase1.log.gz"
    write_synthetic_log(log_path, 20_000, seed=42)
    expected = (DATA_DIR / "phase1_report_seed42_20000.txt").read_text(encoding="utf-8")
    assert render_report(*analyze_access_log(log_path)) + "\n" == expected


def test_summary_document_is_json_ready(sample_log: Path) -> None:
    document = summary_document(*analyze_access_log(sample_log), top=1)
    assert json.loads(json.dumps(document)) == {
        "lines_read": 6,
        "records_parsed": 2,
        "malformed_lines": 4,
        "p95_latency_ms": 1250,
        "status_counts": {"200": 1, "503": 1},
        "top_endpoints": [{"endpoint": "GET /api/products/{id}", "requests": 1, "p95_ms": 23}],
        "malformed_by_reason": {
            "status out of range": 1,
            "unknown method": 1,
            "unrecognized format": 2,
        },
    }
