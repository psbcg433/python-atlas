"""The optimized sales report, reached in five documented steps from ``slow_report.py``.

Every step is a complete ``build_report(row_count, seed) -> str`` that returns **exactly the
same text** as the slow version (``tests/test_reports.py`` checks this); ``benchmark.py``
measures each one. Each step keeps the previous steps' changes and adds one more:

1. **One pass with dict accumulators**: every metric is updated in a single loop over the
   rows, so the nested ``groups x rows`` loops and repeated scans disappear.
2. **Lean rows and exact money**: rows become tuples of small ints, money is integer paise,
   no per-row strings (order id, ISO date, pair key) are built, the text is ``"".join``-ed.
3. **Stream instead of materialize**: aggregate chunk by chunk straight from the generator;
   only one chunk of rows exists at a time.
4. **Concurrent store lookups** (the concurrency step): the 40 store-directory calls run on a
   thread pool while the main thread aggregates; ``time.sleep`` (like socket I/O) releases
   the GIL, so the waits overlap with the CPU work and with each other.
5. **Vectorize with NumPy**: per-chunk grouping with ``np.add.at`` on integer columns.

Run it from this folder::

    python fast_report.py --rows 1000000 --seed 42           # final version (step 5)
    python fast_report.py --rows 1000000 --step 3            # any earlier step
"""

import argparse
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

import slow_report
from common import (
    DEFAULT_ROW_COUNT,
    DEFAULT_SEED,
    MONTH_OF_DAY,
    PRICE_PAISE,
    PRODUCTS,
    REGIONS,
    STORE_CODES,
    YEAR,
    fetch_store_profile,
    generate_chunks,
)

STORE_COUNT, PRODUCT_COUNT, MONTH_COUNT = len(STORE_CODES), len(PRODUCTS), 12
SKU_INDEX = {product.sku: index for index, product in enumerate(PRODUCTS)}
STORE_INDEX = {code: index for index, code in enumerate(STORE_CODES)}
PRICE_LIST = PRICE_PAISE.tolist()  # plain ints: faster than NumPy scalars in a Python loop
MONTH_LIST = MONTH_OF_DAY.tolist()


@dataclass(slots=True)
class SalesSummary:
    """Every total the report needs. Money is integer paise; groups are list positions."""

    order_lines: int = 0
    units: int = 0
    first_day: int | None = None  # day of the year, None when there are no rows
    last_day: int | None = None
    store_paise: list[int] = field(default_factory=lambda: [0] * STORE_COUNT)
    store_lines: list[int] = field(default_factory=lambda: [0] * STORE_COUNT)
    product_units: list[int] = field(default_factory=lambda: [0] * PRODUCT_COUNT)
    product_paise: list[int] = field(default_factory=lambda: [0] * PRODUCT_COUNT)
    month_paise: list[int] = field(default_factory=lambda: [0] * MONTH_COUNT)
    month_lines: list[int] = field(default_factory=lambda: [0] * MONTH_COUNT)
    pair_paise: dict[tuple[int, int], int] = field(default_factory=dict)  # (store, product)

    @property
    def revenue_paise(self) -> int:
        """Grand total: the sum of the per-store totals."""
        return sum(self.store_paise)


# ----- rendering (shared by steps 1-5) -------------------------------------------------------


def format_paise(amount_paise: int) -> str:
    """Integer paise -> '1,234.50' (exact; the same text f'{rupees:,.2f}' gives)."""
    rupees, paise = divmod(amount_paise, 100)
    return f"{rupees:,}.{paise:02d}"


def day_text(day: int | None) -> str:
    """Day of the year -> ISO date ('-' when there are no rows)."""
    return "-" if day is None else (date(YEAR, 1, 1) + timedelta(days=day)).isoformat()


def render_report(summary: SalesSummary, profiles: list[dict[str, str]]) -> str:
    """Build the report text from the totals with one list of lines and one join."""
    revenue = summary.revenue_paise
    lines = [
        f"SALES REPORT {YEAR}",
        "=================",
        f"Order lines: {summary.order_lines:>15,}",
        f"Units sold:  {summary.units:>15,}",
        f"Revenue INR: {format_paise(revenue):>15}",
        f"Period:      {day_text(summary.first_day)} to {day_text(summary.last_day)}",
        "",
        "REVENUE BY REGION",
        f"{'Region':<10}{'Revenue INR':>18}{'Order lines':>13}",
    ]
    region_of = {profile["code"]: profile["region"] for profile in profiles}
    for region in REGIONS:
        members = [STORE_INDEX[code] for code in STORE_CODES if region_of[code] == region]
        region_paise = sum(summary.store_paise[index] for index in members)
        region_lines = sum(summary.store_lines[index] for index in members)
        lines.append(f"{region:<10}{format_paise(region_paise):>18}{region_lines:>13,}")
    lines += [
        "",
        "TOP 10 STORES",
        f"{'Rank':<6}{'Store':<7}{'City':<13}{'Region':<9}{'Revenue INR':>18}",
    ]
    store_order = sorted(
        profiles, key=lambda p: (-summary.store_paise[STORE_INDEX[p["code"]]], p["code"])
    )
    for rank, profile in enumerate(store_order[:10], start=1):
        amount = format_paise(summary.store_paise[STORE_INDEX[profile["code"]]])
        lines.append(
            f"{rank:<6}{profile['code']:<7}{profile['city']:<13}{profile['region']:<9}{amount:>18}"
        )
    lines += [
        "",
        "TOP 10 PRODUCTS",
        f"{'Rank':<6}{'SKU':<9}{'Product':<22}{'Units':>9}{'Revenue INR':>18}",
    ]
    product_order = sorted(
        range(PRODUCT_COUNT), key=lambda i: (-summary.product_paise[i], PRODUCTS[i].sku)
    )
    for rank, index in enumerate(product_order[:10], start=1):
        product, units = PRODUCTS[index], summary.product_units[index]
        amount = format_paise(summary.product_paise[index])
        lines.append(f"{rank:<6}{product.sku:<9}{product.name:<22}{units:>9,}{amount:>18}")
    lines += ["", "MONTHLY REVENUE", f"{'Month':<9}{'Revenue INR':>18}{'Order lines':>13}"]
    for month in range(MONTH_COUNT):
        amount = format_paise(summary.month_paise[month])
        lines.append(f"{YEAR}-{month + 1:02d}  {amount:>18}{summary.month_lines[month]:>13,}")
    lines += ["", "TOP 5 STORE / PRODUCT PAIRS", f"{'Rank':<6}{'Pair':<20}{'Revenue INR':>18}"]
    pairs = [
        (amount, f"{STORE_CODES[store]} / {PRODUCTS[product].sku}")
        for (store, product), amount in summary.pair_paise.items()
        if amount
    ]
    pairs.sort(key=lambda pair: (-pair[0], pair[1]))
    for rank, (amount, key) in enumerate(pairs[:5], start=1):
        lines.append(f"{rank:<6}{key:<20}{format_paise(amount):>18}")
    return "\n".join(lines) + "\n"


# ----- step 1: one pass with dict accumulators -----------------------------------------------


def to_paise(amount_rupees: float) -> int:
    """Convert a float rupee total to integer paise once, at the end (step 1 only)."""
    return round(amount_rupees * 100)


def summarize_rows_single_pass(rows: list[slow_report.Row]) -> SalesSummary:
    """Step 1: the slow version's list of dicts and float money, but one loop for everything."""
    store_revenue = dict.fromkeys(STORE_CODES, 0.0)
    store_lines = dict.fromkeys(STORE_CODES, 0)
    product_revenue = dict.fromkeys(SKU_INDEX, 0.0)
    product_units = dict.fromkeys(SKU_INDEX, 0)
    month_revenue: dict[str, float] = {}
    month_lines: dict[str, int] = {}
    pair_revenue: dict[tuple[str, str], float] = {}
    summary = SalesSummary(order_lines=len(rows))
    dates = []
    for row in rows:
        quantity, store, sku, month = row["quantity"], row["store"], row["sku"], row["date"][:7]
        amount = quantity * row["unit_price"]
        summary.units += quantity
        store_revenue[store] += amount
        store_lines[store] += 1
        product_revenue[sku] += amount
        product_units[sku] += quantity
        month_revenue[month] = month_revenue.get(month, 0.0) + amount
        month_lines[month] = month_lines.get(month, 0) + 1
        pair_revenue[store, sku] = pair_revenue.get((store, sku), 0.0) + amount
        dates.append(row["date"])
    if dates:
        year_start = date(YEAR, 1, 1)
        summary.first_day = (date.fromisoformat(min(dates)) - year_start).days
        summary.last_day = (date.fromisoformat(max(dates)) - year_start).days
    summary.store_paise = [to_paise(store_revenue[code]) for code in STORE_CODES]
    summary.store_lines = [store_lines[code] for code in STORE_CODES]
    summary.product_paise = [to_paise(product_revenue[p.sku]) for p in PRODUCTS]
    summary.product_units = [product_units[p.sku] for p in PRODUCTS]
    months = [f"{YEAR}-{month:02d}" for month in range(1, 13)]
    summary.month_paise = [to_paise(month_revenue.get(month, 0.0)) for month in months]
    summary.month_lines = [month_lines.get(month, 0) for month in months]
    summary.pair_paise = {
        (STORE_INDEX[store], SKU_INDEX[sku]): to_paise(amount)
        for (store, sku), amount in pair_revenue.items()
    }
    return summary


def build_report_step1(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Step 1: single pass over the slow version's rows; profiles still fetched one by one."""
    rows = slow_report.generate_rows(row_count, seed)
    profiles = slow_report.fetch_profiles(STORE_CODES)
    return render_report(summarize_rows_single_pass(rows), profiles)


# ----- step 2: lean rows, integer paise, no per-row strings ----------------------------------

type LeanRow = tuple[int, int, int, int]  # (store index, product index, quantity, day)


def generate_lean_rows(row_count: int, seed: int) -> list[LeanRow]:
    """Step 2: rows as tuples of small ints (no dicts, no strings, no floats)."""
    rows: list[LeanRow] = []
    for chunk in generate_chunks(row_count, seed):
        rows.extend(
            zip(
                chunk.store_index.tolist(),
                chunk.product_index.tolist(),
                chunk.quantity.tolist(),
                chunk.day.tolist(),
                strict=True,
            )
        )
    return rows


def add_rows(summary: SalesSummary, rows: list[LeanRow]) -> None:
    """Add lean rows to the totals in one loop; money stays integer paise (exact)."""
    store_paise, store_lines = summary.store_paise, summary.store_lines  # local aliases
    product_paise, product_units = summary.product_paise, summary.product_units
    month_paise, month_lines, pair_paise = (
        summary.month_paise,
        summary.month_lines,
        summary.pair_paise,
    )
    prices, month_of_day = PRICE_LIST, MONTH_LIST
    units = 0
    for store, product, quantity, day in rows:
        amount = prices[product] * quantity
        units += quantity
        store_paise[store] += amount
        store_lines[store] += 1
        product_paise[product] += amount
        product_units[product] += quantity
        month = month_of_day[day]
        month_paise[month] += amount
        month_lines[month] += 1
        pair_paise[store, product] = pair_paise.get((store, product), 0) + amount
    summary.units += units
    summary.order_lines += len(rows)
    if rows:
        days = [row[3] for row in rows]
        low, high = min(days), max(days)
        summary.first_day = low if summary.first_day is None else min(summary.first_day, low)
        summary.last_day = high if summary.last_day is None else max(summary.last_day, high)


def build_report_step2(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Step 2: one list of lean rows, exact integer money; profiles still sequential."""
    rows = generate_lean_rows(row_count, seed)
    profiles = slow_report.fetch_profiles(STORE_CODES)
    summary = SalesSummary()
    add_rows(summary, rows)
    return render_report(summary, profiles)


# ----- step 3: stream chunk by chunk ---------------------------------------------------------


def summarize_stream(row_count: int, seed: int) -> SalesSummary:
    """Step 3: aggregate each generated chunk and drop it; no list of all rows."""
    summary = SalesSummary()
    for chunk in generate_chunks(row_count, seed):
        columns = (chunk.store_index, chunk.product_index, chunk.quantity, chunk.day)
        add_rows(summary, list(zip(*(column.tolist() for column in columns), strict=True)))
    return summary


def build_report_step3(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Step 3: streaming aggregation; profiles still sequential."""
    summary = summarize_stream(row_count, seed)
    return render_report(summary, slow_report.fetch_profiles(STORE_CODES))


# ----- step 4: concurrent store lookups (overlapped with the aggregation) --------------------


def build_with_concurrent_profiles(
    summarize: Callable[[int, int], SalesSummary], row_count: int, seed: int
) -> str:
    """Start every store lookup on a thread pool, aggregate meanwhile, then collect."""
    with ThreadPoolExecutor(max_workers=len(STORE_CODES), thread_name_prefix="store-api") as pool:
        pending = [pool.submit(fetch_store_profile, code) for code in STORE_CODES]
        summary = summarize(row_count, seed)  # CPU work while the 40 requests wait
        profiles = [future.result() for future in pending]  # input order, not finish order
    return render_report(summary, profiles)


def build_report_step4(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Step 4: streaming aggregation with the store lookups running concurrently."""
    return build_with_concurrent_profiles(summarize_stream, row_count, seed)


# ----- step 5: vectorize the per-chunk grouping with NumPy -----------------------------------


def summarize_vectorized(row_count: int, seed: int) -> SalesSummary:
    """Step 5: group each chunk with np.add.at on int64 columns (exact, no Python loop)."""
    pair_paise = np.zeros((STORE_COUNT, PRODUCT_COUNT), dtype=np.int64)
    pair_units = np.zeros((STORE_COUNT, PRODUCT_COUNT), dtype=np.int64)
    pair_lines = np.zeros((STORE_COUNT, PRODUCT_COUNT), dtype=np.int64)
    month_paise = np.zeros(MONTH_COUNT, dtype=np.int64)
    month_lines = np.zeros(MONTH_COUNT, dtype=np.int64)
    first_day, last_day = None, None
    for chunk in generate_chunks(row_count, seed):
        amount = PRICE_PAISE[chunk.product_index] * chunk.quantity  # int64 paise per row
        where = (chunk.store_index, chunk.product_index)
        np.add.at(pair_paise, where, amount)
        np.add.at(pair_units, where, chunk.quantity)
        np.add.at(pair_lines, where, 1)
        months = MONTH_OF_DAY[chunk.day]
        np.add.at(month_paise, months, amount)
        np.add.at(month_lines, months, 1)
        low, high = int(chunk.day.min()), int(chunk.day.max())
        first_day = low if first_day is None else min(first_day, low)
        last_day = high if last_day is None else max(last_day, high)
    nonzero = zip(*np.nonzero(pair_lines), strict=True)
    return SalesSummary(
        order_lines=int(pair_lines.sum()),
        units=int(pair_units.sum()),
        first_day=first_day,
        last_day=last_day,
        store_paise=pair_paise.sum(axis=1).tolist(),
        store_lines=pair_lines.sum(axis=1).tolist(),
        product_units=pair_units.sum(axis=0).tolist(),
        product_paise=pair_paise.sum(axis=0).tolist(),
        month_paise=month_paise.tolist(),
        month_lines=month_lines.tolist(),
        pair_paise={(int(s), int(p)): int(pair_paise[s, p]) for s, p in nonzero},
    )


def build_report_step5(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Step 5 (final): vectorized aggregation with concurrent store lookups."""
    return build_with_concurrent_profiles(summarize_vectorized, row_count, seed)


build_report = build_report_step5


@dataclass(frozen=True, slots=True)
class Step:
    """One documented optimization step, as benchmark.py reports it."""

    number: int
    change: str
    reason: str
    build: Callable[[int, int], str]


STEPS = (
    Step(
        0,
        "Baseline: `slow_report.py`",
        "nested loops, repeated scans, 1M dicts, float money, string `+=`, 40 sequential API calls",
        slow_report.build_report,
    ),
    Step(
        1,
        "One pass with dict accumulators",
        "O(groups x rows) nested loops and repeated scans become one O(rows) pass",
        build_report_step1,
    ),
    Step(
        2,
        "Lean tuple rows, integer paise, `join`",
        "no per-row dicts, strings or floats: fewer allocations, exact money",
        build_report_step2,
    ),
    Step(
        3,
        "Stream chunks, no list of all rows",
        "only one 100k-row chunk alive at a time: peak memory stops growing with rows",
        build_report_step3,
    ),
    Step(
        4,
        "Concurrent store lookups (thread pool)",
        "40 x 50 ms waits overlap each other and the CPU work "
        "(`sleep`, like socket I/O, releases the GIL)",
        build_report_step4,
    ),
    Step(
        5,
        "Vectorize grouping with NumPy `np.add.at`",
        "per-row Python bytecode replaced by C loops over int64 columns",
        build_report_step5,
    ),
)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: print the report of one step (default: the final one)."""
    parser = argparse.ArgumentParser(description="Optimized sales report")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROW_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--step", type=int, default=5, choices=[step.number for step in STEPS])
    arguments = parser.parse_args(argv)
    start = time.perf_counter()
    report = STEPS[arguments.step].build(arguments.rows, arguments.seed)
    elapsed = time.perf_counter() - start
    print(report, end="")
    print(
        f"fast_report step {arguments.step}: {arguments.rows:,} rows in {elapsed:.2f} s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
