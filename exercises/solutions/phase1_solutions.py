"""Reference solutions for Phase 1 labs.

Run from the repository root:

    uv run python exercises/solutions/phase1_solutions.py
"""

import unicodedata
from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

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


# Lab 1.4 -------------------------------------------------------------------------------------

USERNAME_EXTRA_CHARACTERS = frozenset("_.")


def normalize_username(raw_username: str) -> str:
    """Return the canonical form of a username: NFKC, casefolded, inner whitespace as "_".

    Raises:
        ValueError: if the result is empty or holds a character other than letters, digits,
            "_" and ".".
    """
    folded_username = unicodedata.normalize("NFKC", raw_username).casefold()
    username = "_".join(folded_username.split())
    if not username:
        raise ValueError("username is empty")
    invalid_characters = sorted(
        {
            character
            for character in username
            if not (character.isalnum() or character in USERNAME_EXTRA_CHARACTERS)
        }
    )
    if invalid_characters:
        raise ValueError(f"invalid characters in username: {invalid_characters}")
    return username


RECEIPT_NAME_WIDTH = 20


def format_receipt_line(item_name: str, quantity: int, unit_price: Decimal) -> str:
    """Return a 49-character receipt line: name (20), quantity (4), " x ", price (10), total (12).

    Names longer than the column are cut to 19 characters plus "…".
    """
    if len(item_name) > RECEIPT_NAME_WIDTH:
        item_name = item_name[: RECEIPT_NAME_WIDTH - 1] + "…"
    name_column = f"{item_name:<{RECEIPT_NAME_WIDTH}}"
    line_total = unit_price * quantity
    return f"{name_column}{quantity:>4} x {unit_price:>10,.2f}{line_total:>12,.2f}"


def normalize_search_query(raw_query: str) -> str:
    """Return a casefolded, accent-free query with punctuation removed and single spaces."""
    decomposed_query = unicodedata.normalize("NFKD", raw_query)
    unaccented_query = "".join(
        character for character in decomposed_query if not unicodedata.combining(character)
    )
    folded_query = unaccented_query.casefold()
    spaced_query = "".join(character if character.isalnum() else " " for character in folded_query)
    return " ".join(spaced_query.split())


def check_lab_1_4() -> None:
    """Run the same checks as the Lab 1.4 check cells in the notebook."""
    print("Exercise 1 — normalize_username")
    run_checks(
        [
            ("strip and casefold", lambda: normalize_username("  Asha.Kumar "), "asha.kumar"),
            (
                "inner spaces become _",
                lambda: normalize_username("Ravi   Shankar"),
                "ravi_shankar",
            ),
            ("full-width letters", lambda: normalize_username("ＡＳＨＡ２６"), "asha26"),
            ("ß casefolds to ss", lambda: normalize_username("STRAßE"), "strasse"),
            (
                "combining accent equals precomposed",
                lambda: normalize_username("José") == normalize_username("JOSÉ"),
                True,
            ),
            (
                "blank raises",
                lambda: raised_error_name(lambda: normalize_username("   ")),
                "ValueError",
            ),
            (
                "@ raises",
                lambda: raised_error_name(lambda: normalize_username("asha@home")),
                "ValueError",
            ),
        ]
    )
    print("\nExercise 2 — format_receipt_line")
    run_checks(
        [
            (
                "basic line",
                lambda: format_receipt_line("Masala Dosa", 2, Decimal("120")),
                "Masala Dosa            2 x     120.00      240.00",
            ),
            (
                "long name is truncated with …",
                lambda: format_receipt_line("Paneer Butter Masala Special", 1, Decimal("320.5")),
                "Paneer Butter Masal…   1 x     320.50      320.50",
            ),
            (
                "thousands separators",
                lambda: format_receipt_line("Wedding Catering", 3, Decimal("125000")),
                "Wedding Catering       3 x 125,000.00  375,000.00",
            ),
            (
                "always 49 characters",
                lambda: {
                    len(format_receipt_line(name, count, Decimal(price)))
                    for name, count, price in [("Tea", 1, "10"), ("A" * 40, 99, "9999.99")]
                },
                {49},
            ),
        ]
    )
    print("\nExercise 3 — normalize_search_query")
    run_checks(
        [
            (
                "accents and case",
                lambda: normalize_search_query("  Café   CRÈME! "),
                "cafe creme",
            ),
            (
                "punctuation becomes spaces",
                lambda: normalize_search_query("Masala-Dosa,  Bengaluru"),
                "masala dosa bengaluru",
            ),
            ("full-width text", lambda: normalize_search_query("ＤＯＳＡ ２０２６"), "dosa 2026"),
            (
                "ß and SS match",
                lambda: normalize_search_query("Straße") == normalize_search_query("STRASSE"),
                True,
            ),
            ("empty query", lambda: normalize_search_query(""), ""),
            ("only punctuation", lambda: normalize_search_query("!!! ???"), ""),
        ]
    )


# Lab 1.5 -------------------------------------------------------------------------------------


class Employee(NamedTuple):
    """An employee record for the sorting exercise."""

    name: str
    department: str
    salary: int


SAMPLE_EMPLOYEES = [
    Employee("Asha", "Engineering", 120_000),
    Employee("Ravi", "Sales", 80_000),
    Employee("Meena", "Engineering", 150_000),
    Employee("John", "Sales", 80_000),
    Employee("Fatima", "Design", 95_000),
    Employee("Arjun", "Engineering", 120_000),
]


def sort_employees_multipass(employees: list[Employee]) -> list[Employee]:
    """Sort by department, salary (high first), name using stable multi-pass sorting.

    Passes run from the least important key to the most important one; stability keeps the
    earlier order among ties.
    """
    by_name = sorted(employees, key=lambda employee: employee.name)
    by_salary_descending = sorted(by_name, key=lambda employee: employee.salary, reverse=True)
    return sorted(by_salary_descending, key=lambda employee: employee.department)


def sort_employees_tuple_key(employees: list[Employee]) -> list[Employee]:
    """Sort by department, salary (high first), name using one tuple key."""
    return sorted(
        employees,
        key=lambda employee: (employee.department, -employee.salary, employee.name),
    )


def transpose[T](matrix: list[list[T]]) -> list[list[T]]:
    """Return the transpose of a rectangular matrix given as a list of rows.

    Raises:
        ValueError: if the rows have different lengths.
    """
    return [list(column) for column in zip(*matrix, strict=True)]


def dedupe_preserving_order[T](items: Iterable[T]) -> list[T]:
    """Return the items without duplicates, keeping first occurrences in order."""
    seen_items: set[T] = set()
    unique_items: list[T] = []
    for item in items:
        if item not in seen_items:
            seen_items.add(item)
            unique_items.append(item)
    return unique_items


def employee_names(employees: list[Employee]) -> list[str]:
    """Return just the names, in order."""
    return [employee.name for employee in employees]


def returns_new_list(sort_function: Callable[[list[Employee]], list[Employee]]) -> bool:
    """Return True if sort_function returns a new list and leaves its argument alone."""
    employees_argument = list(SAMPLE_EMPLOYEES)
    sorted_employees = sort_function(employees_argument)
    return sorted_employees is not employees_argument and employees_argument == SAMPLE_EMPLOYEES


def check_lab_1_5() -> None:
    """Run the same checks as the Lab 1.5 check cells in the notebook."""
    print("Exercise 1 — sort employee records")
    expected_employee_order = ["Fatima", "Meena", "Arjun", "Asha", "John", "Ravi"]
    run_checks(
        [
            (
                "multi-pass order",
                lambda: employee_names(sort_employees_multipass(SAMPLE_EMPLOYEES)),
                expected_employee_order,
            ),
            (
                "tuple-key order",
                lambda: employee_names(sort_employees_tuple_key(SAMPLE_EMPLOYEES)),
                expected_employee_order,
            ),
            (
                "both versions agree",
                lambda: (
                    sort_employees_multipass(SAMPLE_EMPLOYEES)
                    == sort_employees_tuple_key(SAMPLE_EMPLOYEES)
                ),
                True,
            ),
            (
                "multi-pass returns a new list",
                lambda: returns_new_list(sort_employees_multipass),
                True,
            ),
            (
                "tuple-key returns a new list",
                lambda: returns_new_list(sort_employees_tuple_key),
                True,
            ),
            ("empty list", lambda: sort_employees_tuple_key([]), []),
        ]
    )
    print("\nExercise 2 — transpose")
    run_checks(
        [
            (
                "2x3 becomes 3x2",
                lambda: transpose([[1, 2, 3], [4, 5, 6]]),
                [[1, 4], [2, 5], [3, 6]],
            ),
            ("square", lambda: transpose([[1, 2], [3, 4]]), [[1, 3], [2, 4]]),
            ("single row", lambda: transpose([["a", "b"]]), [["a"], ["b"]]),
            ("empty matrix", lambda: transpose([]), []),
            ("rows are lists", lambda: type(transpose([[1, 2]])[0]).__name__, "list"),
            (
                "ragged rows raise",
                lambda: raised_error_name(lambda: transpose([[1, 2], [3]])),
                "ValueError",
            ),
        ]
    )
    print("\nExercise 3 — dedupe_preserving_order")
    run_checks(
        [
            ("ints", lambda: dedupe_preserving_order([3, 1, 3, 2, 1]), [3, 1, 2]),
            (
                "strings",
                lambda: dedupe_preserving_order(["b", "a", "b", "c", "a"]),
                ["b", "a", "c"],
            ),
            ("empty", lambda: dedupe_preserving_order([]), []),
            (
                "one-shot iterator",
                lambda: dedupe_preserving_order(iter("mississippi")),
                ["m", "i", "s", "p"],
            ),
            (
                "1, 1.0 and True are equal",
                lambda: dedupe_preserving_order([1, 1.0, True, 2]),
                [1, 2],
            ),
            (
                "tuples",
                lambda: dedupe_preserving_order([(1, 2), (1, 2), (2, 1)]),
                [(1, 2), (2, 1)],
            ),
        ]
    )


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 1.3", check_lab_1_3),
        ("Lab 1.4", check_lab_1_4),
        ("Lab 1.5", check_lab_1_5),
    ]:
        print(f"\n=== {lab_title} ===")
        check_lab()
