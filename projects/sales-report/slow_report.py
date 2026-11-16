"""The deliberately slow sales report: the Phase 5 Project baseline.

Every pattern marked ``# SLOW:`` is a real mistake found in production scripts, kept here on
purpose so that ``fast_report.py`` has something to fix:

- all rows are materialized as a list of one million dicts, each with per-row strings;
- money is a float (``price_paise / 100``);
- every metric is its own scan over all rows (repeated scans);
- per-store, per-product and per-month totals use nested loops (O(groups x rows));
- per-row keys and the report text are built by string concatenation;
- the store directory API is called once per store, one call after another.

Run it from this folder (prints the report and the time it took)::

    python slow_report.py --rows 1000000 --seed 42
"""

import argparse
import sys
import time
from datetime import date, timedelta

from common import (
    DEFAULT_ROW_COUNT,
    DEFAULT_SEED,
    PRODUCTS,
    REGIONS,
    STORE_CODES,
    YEAR,
    fetch_store_profile,
    generate_chunks,
)

type Row = dict[str, object]


def generate_rows(row_count: int, seed: int) -> list[Row]:
    """Materialize every generated sale as a dict with float money and string fields."""
    rows: list[Row] = []  # SLOW: one million dicts held in memory at once
    year_start = date(YEAR, 1, 1)
    for chunk in generate_chunks(row_count, seed):
        for position in range(len(chunk)):
            product = PRODUCTS[chunk.product_index[position]]
            order_number = chunk.first_order_number + position
            rows.append(
                {
                    "order_id": "ORD-" + str(order_number).zfill(7),  # SLOW: per-row string
                    "store": STORE_CODES[chunk.store_index[position]],
                    "sku": product.sku,
                    "quantity": int(chunk.quantity[position]),
                    "unit_price": product.price_paise / 100,  # SLOW: float money
                    "date": (year_start + timedelta(days=int(chunk.day[position]))).isoformat(),
                }
            )
    return rows


def fetch_profiles(store_codes: tuple[str, ...]) -> list[dict[str, str]]:
    """Call the store directory API for every store, one call after another."""
    profiles = []
    for store_code in store_codes:  # SLOW: sequential network waits
        profiles.append(fetch_store_profile(store_code))
    return profiles


def money(amount: float) -> str:
    """Format a float amount of rupees with thousands separators and two decimals."""
    return f"{amount:,.2f}"


def build_report(row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> str:
    """Generate the rows, fetch the store profiles, compute every metric and render the text."""
    rows = generate_rows(row_count, seed)
    profiles = fetch_profiles(STORE_CODES)

    # SLOW: repeated scans, one full pass over the rows per header metric
    total_units = 0
    for row in rows:
        total_units += row["quantity"]
    total_revenue = 0.0
    for row in rows:
        total_revenue += row["quantity"] * row["unit_price"]
    first_date = min([row["date"] for row in rows]) if rows else "-"
    last_date = max([row["date"] for row in rows]) if rows else "-"

    report = ""  # SLOW: the report text is built with +=
    report += "SALES REPORT " + str(YEAR) + "\n"
    report += "=================\n"
    report += "Order lines: " + f"{len(rows):>15,}" + "\n"
    report += "Units sold:  " + f"{total_units:>15,}" + "\n"
    report += "Revenue INR: " + f"{money(total_revenue):>15}" + "\n"
    report += "Period:      " + first_date + " to " + last_date + "\n"
    report += region_section(rows, profiles)
    report += store_section(rows, profiles)
    report += product_section(rows)
    report += month_section(rows)
    report += pair_section(rows)
    return report


def region_section(rows: list[Row], profiles: list[dict[str, str]]) -> str:
    """Revenue and order lines per region: one scan of all rows per region."""
    text = "\nREVENUE BY REGION\n"
    text += f"{'Region':<10}{'Revenue INR':>18}{'Order lines':>13}\n"
    for region in REGIONS:
        region_stores = [profile["code"] for profile in profiles if profile["region"] == region]
        revenue = 0.0
        order_lines = 0
        for row in rows:  # SLOW: nested loop, and `in` on a list
            if row["store"] in region_stores:
                revenue += row["quantity"] * row["unit_price"]
                order_lines += 1
        text += f"{region:<10}{money(revenue):>18}{order_lines:>13,}\n"
    return text


def store_section(rows: list[Row], profiles: list[dict[str, str]]) -> str:
    """Top 10 stores by revenue: one scan of all rows per store."""
    store_revenue = []
    for profile in profiles:
        revenue = 0.0
        for row in rows:  # SLOW: nested loop, 40 stores x all rows
            if row["store"] == profile["code"]:
                revenue += row["quantity"] * row["unit_price"]
        store_revenue.append((profile, revenue))
    store_revenue.sort(key=lambda pair: (-round(pair[1], 2), pair[0]["code"]))
    text = "\nTOP 10 STORES\n"
    text += f"{'Rank':<6}{'Store':<7}{'City':<13}{'Region':<9}{'Revenue INR':>18}\n"
    for rank, (profile, revenue) in enumerate(store_revenue[:10], start=1):
        text += f"{rank:<6}{profile['code']:<7}{profile['city']:<13}{profile['region']:<9}"
        text += f"{money(revenue):>18}\n"
    return text


def product_section(rows: list[Row]) -> str:
    """Top 10 products by revenue: one scan of all rows per product."""
    product_totals = []
    for product in PRODUCTS:
        units = 0
        revenue = 0.0
        for row in rows:  # SLOW: nested loop, 60 products x all rows
            if row["sku"] == product.sku:
                units += row["quantity"]
                revenue += row["quantity"] * row["unit_price"]
        product_totals.append((product, units, revenue))
    product_totals.sort(key=lambda entry: (-round(entry[2], 2), entry[0].sku))
    text = "\nTOP 10 PRODUCTS\n"
    text += f"{'Rank':<6}{'SKU':<9}{'Product':<22}{'Units':>9}{'Revenue INR':>18}\n"
    for rank, (product, units, revenue) in enumerate(product_totals[:10], start=1):
        text += f"{rank:<6}{product.sku:<9}{product.name:<22}{units:>9,}{money(revenue):>18}\n"
    return text


def month_section(rows: list[Row]) -> str:
    """Revenue and order lines per month: one scan of all rows per month."""
    text = "\nMONTHLY REVENUE\n"
    text += f"{'Month':<9}{'Revenue INR':>18}{'Order lines':>13}\n"
    for month in range(1, 13):
        prefix = str(YEAR) + "-" + str(month).zfill(2)
        revenue = 0.0
        order_lines = 0
        for row in rows:  # SLOW: nested loop, 12 months x all rows, string prefix tests
            if row["date"].startswith(prefix):
                revenue += row["quantity"] * row["unit_price"]
                order_lines += 1
        text += f"{prefix:<9}{money(revenue):>18}{order_lines:>13,}\n"
    return text


def pair_section(rows: list[Row]) -> str:
    """Top 5 store/product pairs by revenue, keyed by a concatenated string per row."""
    pair_revenue: dict[str, float] = {}
    for row in rows:
        key = row["store"] + " / " + row["sku"]  # SLOW: a new string for every row
        if key not in pair_revenue:
            pair_revenue[key] = 0.0
        pair_revenue[key] = pair_revenue[key] + row["quantity"] * row["unit_price"]
    ranked = sorted(pair_revenue.items(), key=lambda item: (-round(item[1], 2), item[0]))
    text = "\nTOP 5 STORE / PRODUCT PAIRS\n"
    text += f"{'Rank':<6}{'Pair':<20}{'Revenue INR':>18}\n"
    for rank, (key, revenue) in enumerate(ranked[:5], start=1):
        text += f"{rank:<6}{key:<20}{money(revenue):>18}\n"
    return text


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: print the report, then the time it took (to stderr)."""
    parser = argparse.ArgumentParser(description="Deliberately slow sales report")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROW_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args(argv)
    start = time.perf_counter()
    report = build_report(arguments.rows, arguments.seed)
    elapsed = time.perf_counter() - start
    print(report, end="")
    print(f"slow_report: {arguments.rows:,} rows in {elapsed:.2f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
