"""The optimized report must be byte-for-byte the slow report, at every step."""

import time
from decimal import Decimal

import pytest

import common
import fast_report
import slow_report

SIZES = [(0, 1), (1, 2), (997, 3), (25_000, 4), (130_000, 42)]  # 130k spans two chunks


@pytest.mark.parametrize(("row_count", "seed"), SIZES)
def test_every_step_matches_the_slow_report(row_count: int, seed: int) -> None:
    expected = slow_report.build_report(row_count, seed)
    for step in fast_report.STEPS[1:]:
        assert step.build(row_count, seed) == expected, f"step {step.number} differs"


def test_final_version_is_the_last_step() -> None:
    assert fast_report.build_report is fast_report.STEPS[-1].build
    assert [step.number for step in fast_report.STEPS] == [0, 1, 2, 3, 4, 5]


def test_generator_is_deterministic_and_seed_dependent() -> None:
    def first_chunk(seed: int) -> list[int]:
        chunk = next(common.generate_chunks(1_000, seed))
        return chunk.product_index.tolist()

    assert first_chunk(42) == first_chunk(42)
    assert first_chunk(42) != first_chunk(43)
    assert sum(len(chunk) for chunk in common.generate_chunks(250_001, 1)) == 250_001


def test_money_formatting_is_exact() -> None:
    assert fast_report.format_paise(0) == "0.00"
    assert fast_report.format_paise(5) == "0.05"
    assert fast_report.format_paise(123_456_789) == "1,234,567.89"
    for paise in (1, 10, 99, 100, 101, 2**40 + 7):
        assert fast_report.format_paise(paise) == f"{Decimal(paise) / 100:,.2f}"


def test_grand_total_equals_exact_sum() -> None:
    chunks = list(common.generate_chunks(5_000, 9))
    exact = sum(
        int((common.PRICE_PAISE[chunk.product_index] * chunk.quantity).sum()) for chunk in chunks
    )
    assert fast_report.summarize_vectorized(5_000, 9).revenue_paise == exact


def test_store_lookups_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_NETWORK_DELAY", "0.05")
    start = time.perf_counter()
    fast_report.build_report_step5(1_000, 1)
    assert time.perf_counter() - start < 40 * 0.05 / 4  # far below the sequential 2 s


def test_negative_row_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="row_count"):
        next(common.generate_chunks(-1, 1))
