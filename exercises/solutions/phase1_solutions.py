"""Reference solutions for Phase 1 labs.

Run from the repository root:

    uv run python exercises/solutions/phase1_solutions.py
"""

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

type TestCase = tuple[str, Callable[[], object], object]


def run_checks(test_cases: list[TestCase]) -> None:
    """Run (label, thunk, expected) cases and print PASS/FAIL for each. Never raises."""
    passed_count = 0
    for label, thunk, expected in test_cases:
        try:
            actual = thunk()
        except Exception as error:  # a check must never stop the script
            print(f"FAIL  {label}: raised {type(error).__name__}: {error}")
            continue
        if actual == expected:
            passed_count += 1
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label}: expected {expected!r}, got {actual!r}")
    print(f"{passed_count}/{len(test_cases)} checks passed")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


# Lab 1.3 -------------------------------------------------------------------------------------

PAISE = Decimal("0.01")


def split_bill(total_amount: str, people_count: int) -> list[Decimal]:
    """Split a rupee amount into people_count parts, exact to the paisa.

    The parts differ by at most one paisa and always sum to the total; the leftover paise go to
    the first people in the list.

    Raises:
        ValueError: if people_count is less than 1.
    """
    if people_count < 1:
        raise ValueError(f"people_count must be at least 1, got {people_count}")
    total_in_paise = int(Decimal(total_amount).quantize(PAISE, rounding=ROUND_HALF_UP) * 100)
    base_share_in_paise, leftover_paise = divmod(total_in_paise, people_count)
    return [
        (Decimal(base_share_in_paise + (1 if index < leftover_paise else 0)) / 100).quantize(PAISE)
        for index in range(people_count)
    ]


def invoice_total_decimal(
    line_items: list[tuple[str, int]], gst_rate_percent: str = "18"
) -> Decimal:
    """Return the invoice total: each line's net amount plus its GST rounded half-up to paise.

    Args:
        line_items: (unit price as a string, quantity) pairs.
        gst_rate_percent: GST rate as a string, e.g. "18".
    """
    gst_rate = Decimal(gst_rate_percent) / 100
    invoice_total = Decimal("0.00")
    for unit_price, quantity in line_items:
        line_net_amount = Decimal(unit_price) * quantity
        line_gst = (line_net_amount * gst_rate).quantize(PAISE, rounding=ROUND_HALF_UP)
        invoice_total += line_net_amount + line_gst
    return invoice_total.quantize(PAISE)


def invoice_total_float(
    line_items: list[tuple[float, int]], gst_rate_percent: float = 18.0
) -> float:
    """Return the same invoice total computed with float and round(), to show the drift.

    Args:
        line_items: (unit price, quantity) pairs.
        gst_rate_percent: GST rate, e.g. 18.0.
    """
    invoice_total = 0.0
    for unit_price, quantity in line_items:
        line_net_amount = unit_price * quantity
        line_gst = round(line_net_amount * gst_rate_percent / 100, 2)
        invoice_total += line_net_amount + line_gst
    return invoice_total


SAMPLE_LINE_ITEMS = [("19.99", 3), ("0.10", 7), ("2.75", 1), ("12.25", 2), ("0.25", 1), ("5.25", 1)]


def check_lab_1_3() -> None:
    """Run the same checks as the Lab 1.3 check cells in the notebook."""
    print("Exercise 1 — split_bill")
    run_checks(
        [
            (
                "100 between 3",
                lambda: split_bill("100", 3),
                [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")],
            ),
            ("parts sum to the total", lambda: sum(split_bill("1000.01", 7)), Decimal("1000.01")),
            ("one part per person", lambda: len(split_bill("10", 4)), 4),
            (
                "parts differ by at most one paisa",
                lambda: max(split_bill("0.05", 3)) - min(split_bill("0.05", 3)) <= PAISE,
                True,
            ),
            (
                "every part has two decimal places",
                lambda: {part.as_tuple().exponent for part in split_bill("90", 4)},
                {-2},
            ),
            ("returns Decimal", lambda: type(split_bill("1", 1)[0]).__name__, "Decimal"),
            (
                "zero people raises",
                lambda: raised_error_name(lambda: split_bill("10", 0)),
                "ValueError",
            ),
        ]
    )
    print("\nExercise 2 — invoice calculator")
    float_line_items = [(float(unit_price), quantity) for unit_price, quantity in SAMPLE_LINE_ITEMS]
    run_checks(
        [
            ("empty invoice", lambda: invoice_total_decimal([]), Decimal("0.00")),
            ("one line, 18% GST", lambda: invoice_total_decimal([("100", 2)]), Decimal("236.00")),
            ("GST rounds half up", lambda: invoice_total_decimal([("1.25", 1)]), Decimal("1.48")),
            (
                "custom rate 5%",
                lambda: invoice_total_decimal([("10.10", 1)], "5"),
                Decimal("10.61"),
            ),
            ("sample invoice", lambda: invoice_total_decimal(SAMPLE_LINE_ITEMS), Decimal("110.25")),
            ("float: one line, 18% GST", lambda: invoice_total_float([(100.0, 2)]), 236.0),
            (
                "float: round() loses a paisa on 2.75",
                lambda: invoice_total_float([(2.75, 1)]),
                3.24,
            ),
            (
                "float: sample invoice drifts from the exact total",
                lambda: (
                    invoice_total_float(float_line_items)
                    != float(invoice_total_decimal(SAMPLE_LINE_ITEMS))
                ),
                True,
            ),
        ]
    )
    exact_total = invoice_total_decimal(SAMPLE_LINE_ITEMS)
    float_total = invoice_total_float(float_line_items)
    print(f"\n{exact_total=}\n{float_total=}\n{float_total == float(exact_total)=}")


if __name__ == "__main__":
    check_lab_1_3()
