"""Reference solutions for Phase 1 labs.

Run from the repository root:

    uv run python exercises/solutions/phase1_solutions.py
"""

import copy
import datetime as dt
import inspect
import io
import operator
import re
import unicodedata
from collections import ChainMap, Counter, OrderedDict, defaultdict, deque
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import IO, Any, NamedTuple
from urllib.parse import urlencode

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


# Lab 1.6 -------------------------------------------------------------------------------------


class Order(NamedTuple):
    """One order line for the Lab 1.6 exercises."""

    order_id: int
    customer: str
    sku: str
    quantity: int


SAMPLE_ORDERS = [
    Order(1001, "asha", "TEA-500G", 2),
    Order(1002, "ravi", "RICE-5KG", 1),
    Order(1003, "asha", "GHEE-1L", 1),
    Order(1004, "meena", "TEA-500G", 3),
    Order(1005, "ravi", "TEA-500G", 1),
    Order(1006, "john", "SOAP-3PK", 4),
    Order(1007, "meena", "RICE-5KG", 2),
    Order(1008, "asha", "DAL-1KG", 2),
]
PRODUCT_CATALOG: Mapping[str, Decimal] = frozendict(
    {
        "TEA-500G": Decimal("249.00"),
        "RICE-5KG": Decimal("525.50"),
        "GHEE-1L": Decimal("640.00"),
        "DAL-1KG": Decimal("162.25"),
    }
)
WORD_PATTERN = re.compile(r"[^\W_]+")


def group_orders_by_customer(orders: Iterable[Order]) -> dict[str, list[Order]]:
    """Return {customer: [their orders in input order]} as a plain dict."""
    orders_by_customer: defaultdict[str, list[Order]] = defaultdict(list)
    for order in orders:
        orders_by_customer[order.customer].append(order)
    return dict(orders_by_customer)


def top_k_words(text: str, k: int) -> list[tuple[str, int]]:
    """Return the k most frequent words, ties broken alphabetically."""
    if k <= 0:
        return []
    word_counts = Counter(WORD_PATTERN.findall(text.casefold()))
    ranked_words = sorted(word_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked_words[:k]


def merge_configs(
    defaults: Mapping[str, object], env: Mapping[str, object], cli: Mapping[str, object]
) -> ChainMap[str, object]:
    """Layer cli > env > defaults; None in cli means "not given"."""
    given_cli_values = {key: value for key, value in cli.items() if value is not None}
    return ChainMap({}, given_cli_values, env, defaults)


class LRUCache:
    """A fixed-capacity least-recently-used cache built on OrderedDict."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}")
        self.capacity = capacity
        self._entries: OrderedDict[Hashable, object] = OrderedDict()

    def get(self, key: Hashable, default: object = None) -> object:
        """Return the cached value (marking it recent) or default."""
        if key not in self._entries:
            return default
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: Hashable, value: object) -> None:
        """Store value, evicting the least recently used key if over capacity."""
        self._entries[key] = value
        self._entries.move_to_end(key)
        if len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries


def analyze_orders(orders: Iterable[Order], catalog: Mapping[str, Decimal]) -> dict[str, object]:
    """Summarise orders: revenue, top SKUs, customers, recent IDs, unknown SKUs."""
    revenue_by_customer: defaultdict[str, Decimal] = defaultdict(Decimal)
    units_by_sku: Counter[str] = Counter()
    customers: set[str] = set()
    recent_order_ids: deque[int] = deque(maxlen=5)
    unknown_skus: set[str] = set()
    for order in orders:
        customers.add(order.customer)
        recent_order_ids.append(order.order_id)
        if order.sku not in catalog:
            unknown_skus.add(order.sku)
            continue
        revenue_by_customer[order.customer] += catalog[order.sku] * order.quantity
        units_by_sku[order.sku] += order.quantity
    return {
        "revenue_by_customer": dict(revenue_by_customer),
        "top_skus": units_by_sku.most_common(3),
        "unique_customer_count": len(customers),
        "recent_order_ids": list(recent_order_ids),
        "unknown_skus": sorted(unknown_skus),
    }


DEFAULT_CONFIG = {"host": "localhost", "port": 8000, "debug": False, "log_level": "INFO"}
ENV_CONFIG = {"port": 9000, "log_level": "WARNING"}
CLI_CONFIG = {"debug": True, "port": None}


def writes_leave_inputs_alone() -> bool:
    """Write through merge_configs' result and check that no input dict changed."""
    inputs_before = (dict(DEFAULT_CONFIG), dict(ENV_CONFIG), dict(CLI_CONFIG))
    merged_config = merge_configs(DEFAULT_CONFIG, ENV_CONFIG, CLI_CONFIG)
    merged_config["host"] = "example.in"
    merged_config["timeout"] = 30
    return (DEFAULT_CONFIG, ENV_CONFIG, CLI_CONFIG) == inputs_before


def lru_basic_trace() -> list[object]:
    """get refreshes 'a', so putting 'c' evicts 'b'."""
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    first_get = cache.get("a")
    cache.put("c", 3)
    return [first_get, cache.get("b"), cache.get("c"), len(cache), "a" in cache]


def lru_update_trace() -> list[object]:
    """Updating 'a' refreshes it, so putting 'c' evicts 'b'."""
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    return [cache.get("a"), "b" in cache, len(cache)]


def lru_contains_trace() -> bool:
    """Membership does not refresh 'a', so putting 'c' evicts it."""
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    _ = "a" in cache
    cache.put("c", 3)
    return "a" in cache


def check_lab_1_6() -> None:
    """Run the same checks as the Lab 1.6 check cells in the notebook."""
    print("Exercise 1 — group_orders_by_customer")
    run_checks(
        [
            (
                "order ids per customer",
                lambda: {
                    customer: [order.order_id for order in customer_orders]
                    for customer, customer_orders in group_orders_by_customer(SAMPLE_ORDERS).items()
                },
                {
                    "asha": [1001, 1003, 1008],
                    "ravi": [1002, 1005],
                    "meena": [1004, 1007],
                    "john": [1006],
                },
            ),
            (
                "customers in first-seen order",
                lambda: list(group_orders_by_customer(SAMPLE_ORDERS)),
                ["asha", "ravi", "meena", "john"],
            ),
            (
                "returns a plain dict",
                lambda: type(group_orders_by_customer(SAMPLE_ORDERS)).__name__,
                "dict",
            ),
            (
                "missing customer raises",
                lambda: raised_error_name(lambda: group_orders_by_customer(SAMPLE_ORDERS)["zoe"]),
                "KeyError",
            ),
            (
                "accepts an iterator",
                lambda: list(group_orders_by_customer(iter(SAMPLE_ORDERS[:2]))),
                ["asha", "ravi"],
            ),
            ("no orders", lambda: group_orders_by_customer([]), {}),
        ]
    )
    print("\nExercise 2 — top_k_words")
    nursery_text = "The cat and the hat. THE CAT sat; a bat sat!"
    run_checks(
        [
            (
                "top 3",
                lambda: top_k_words(nursery_text, 3),
                [("the", 3), ("cat", 2), ("sat", 2)],
            ),
            (
                "ties alphabetical",
                lambda: top_k_words(nursery_text, 5),
                [("the", 3), ("cat", 2), ("sat", 2), ("a", 1), ("and", 1)],
            ),
            ("k larger than vocabulary", lambda: len(top_k_words(nursery_text, 50)), 7),
            ("k = 0", lambda: top_k_words(nursery_text, 0), []),
            ("empty text", lambda: top_k_words("", 3), []),
            (
                "caseless and unicode",
                lambda: top_k_words("Café café CAFÉ, tea", 1),
                [("café", 3)],
            ),
            (
                "underscore splits words",
                lambda: top_k_words("snake_case snake", 1),
                [("snake", 2)],
            ),
        ]
    )
    print("\nExercise 3 — merge_configs")
    run_checks(
        [
            (
                "returns a ChainMap",
                lambda: type(merge_configs(DEFAULT_CONFIG, ENV_CONFIG, CLI_CONFIG)).__name__,
                "ChainMap",
            ),
            (
                "precedence cli > env > defaults",
                lambda: dict(merge_configs(DEFAULT_CONFIG, ENV_CONFIG, CLI_CONFIG)),
                {"host": "localhost", "port": 9000, "debug": True, "log_level": "WARNING"},
            ),
            (
                "None in cli is ignored",
                lambda: merge_configs(DEFAULT_CONFIG, ENV_CONFIG, CLI_CONFIG)["port"],
                9000,
            ),
            ("writes leave inputs alone", writes_leave_inputs_alone, True),
            ("empty layers", lambda: dict(merge_configs({"a": 1}, {}, {})), {"a": 1}),
        ]
    )
    print("\nExercise 4 — LRUCache")
    run_checks(
        [
            ("get refreshes recency", lru_basic_trace, [1, None, 3, 2, True]),
            ("put updates and refreshes", lru_update_trace, [10, False, 2]),
            ("in does not refresh", lru_contains_trace, False),
            ("get default on miss", lambda: LRUCache(1).get("x", "fallback"), "fallback"),
            ("capacity 0 raises", lambda: raised_error_name(lambda: LRUCache(0)), "ValueError"),
        ]
    )
    print("\nExercise 5 — analyze_orders")
    run_checks(
        [
            (
                "revenue by customer",
                lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["revenue_by_customer"],
                {
                    "asha": Decimal("1462.50"),
                    "ravi": Decimal("774.50"),
                    "meena": Decimal("1798.00"),
                },
            ),
            (
                "top 3 SKUs by units",
                lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["top_skus"],
                [("TEA-500G", 6), ("RICE-5KG", 3), ("DAL-1KG", 2)],
            ),
            (
                "unique customers",
                lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["unique_customer_count"],
                4,
            ),
            (
                "last 5 order ids",
                lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["recent_order_ids"],
                [1004, 1005, 1006, 1007, 1008],
            ),
            (
                "unknown SKUs",
                lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["unknown_skus"],
                ["SOAP-3PK"],
            ),
            (
                "revenue is a plain dict",
                lambda: (
                    type(
                        analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["revenue_by_customer"]
                    ).__name__
                ),
                "dict",
            ),
            (
                "no orders",
                lambda: analyze_orders([], PRODUCT_CATALOG),
                {
                    "revenue_by_customer": {},
                    "top_skus": [],
                    "unique_customer_count": 0,
                    "recent_order_ids": [],
                    "unknown_skus": [],
                },
            ),
        ]
    )


# Lab 1.7 -------------------------------------------------------------------------------------


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict with override merged into base recursively."""
    merged = {key: copy.deepcopy(value) for key, value in base.items()}
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, Mapping):
            merged[key] = deep_merge(base_value, override_value)
        else:
            merged[key] = copy.deepcopy(override_value)
    return merged


class PriceChange(NamedTuple):
    """One changed line found by diff_orders."""

    order_id: int
    sku: str
    old_unit_price: Decimal
    new_unit_price: Decimal


def make_sample_orders() -> list[dict[str, Any]]:
    """Return fresh nested order data for Lab 1.7, exercise 2."""
    return [
        {
            "order_id": 1001,
            "customer": "asha",
            "lines": [
                {"sku": "TEA-500G", "unit_price": Decimal("249.00"), "quantity": 2},
                {"sku": "GHEE-1L", "unit_price": Decimal("640.00"), "quantity": 1},
            ],
        },
        {
            "order_id": 1002,
            "customer": "ravi",
            "lines": [{"sku": "RICE-5KG", "unit_price": Decimal("525.50"), "quantity": 1}],
        },
    ]


def apply_discounts_in_place(
    orders: list[dict[str, Any]], discount_percent_by_sku: Mapping[str, int]
) -> None:
    """Legacy code: reduce unit prices inside orders, rounded to the paisa."""
    for order in orders:
        for line in order["lines"]:
            discount_percent = discount_percent_by_sku.get(line["sku"], 0)
            discounted = line["unit_price"] * (100 - discount_percent) / 100
            line["unit_price"] = discounted.quantize(PAISE, rounding=ROUND_HALF_UP)


def diff_orders(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[PriceChange]:
    """Return a PriceChange for every line whose unit price differs."""
    changes = []
    for order_before, order_after in zip(before, after, strict=True):
        for line_before, line_after in zip(
            order_before["lines"], order_after["lines"], strict=True
        ):
            if line_before["unit_price"] != line_after["unit_price"]:
                changes.append(
                    PriceChange(
                        order_before["order_id"],
                        line_before["sku"],
                        line_before["unit_price"],
                        line_after["unit_price"],
                    )
                )
    return changes


def discount_and_diff(
    orders: list[dict[str, Any]], discount_percent_by_sku: Mapping[str, int]
) -> list[PriceChange]:
    """Snapshot orders, apply discounts in place, return what changed."""
    snapshot = copy.deepcopy(orders)
    apply_discounts_in_place(orders, discount_percent_by_sku)
    return diff_orders(snapshot, orders)


def make_merge_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return fresh (base, override) config dicts for the deep_merge checks."""
    base_settings = {
        "app": {"name": "shop", "debug": False},
        "database": {"host": "db.local", "pool_sizes": [5, 10]},
        "features": ["search"],
    }
    override_settings = {
        "app": {"debug": True},
        "database": {"host": "staging-db.local"},
        "features": ["search", "wishlist"],
        "region": "ap-south-1",
    }
    return base_settings, override_settings


def merge_shares_nothing() -> bool:
    """Mutate deep_merge's result and check that no input object changed or is shared."""
    base_settings, override_settings = make_merge_inputs()
    inputs_before = copy.deepcopy((base_settings, override_settings))
    merged = deep_merge(base_settings, override_settings)
    shares_objects = (
        merged is base_settings
        or merged["app"] is base_settings["app"]
        or merged["database"] is base_settings["database"]
        or merged["database"]["pool_sizes"] is base_settings["database"]["pool_sizes"]
        or merged["features"] is override_settings["features"]
    )
    merged["database"]["pool_sizes"].append(99)
    merged["features"].append("cart")
    merged["app"]["name"] = "changed"
    return not shares_objects and (base_settings, override_settings) == inputs_before


SAMPLE_DISCOUNTS = {"TEA-500G": 10, "RICE-5KG": 5}


def orders_after_discount() -> list[dict[str, Any]]:
    """Run discount_and_diff on fresh orders and return the (mutated) orders."""
    live_orders = make_sample_orders()
    discount_and_diff(live_orders, SAMPLE_DISCOUNTS)
    return live_orders


def orders_with_rice_at_one_rupee() -> list[dict[str, Any]]:
    """Return fresh orders with the rice line edited by hand."""
    edited_orders = make_sample_orders()
    edited_orders[1]["lines"][0]["unit_price"] = Decimal("1.00")
    return edited_orders


def check_lab_1_7() -> None:
    """Run the same checks as the Lab 1.7 check cells in the notebook."""
    print("Exercise 1 — deep_merge")
    run_checks(
        [
            (
                "nested merge",
                lambda: deep_merge(*make_merge_inputs()),
                {
                    "app": {"name": "shop", "debug": True},
                    "database": {"host": "staging-db.local", "pool_sizes": [5, 10]},
                    "features": ["search", "wishlist"],
                    "region": "ap-south-1",
                },
            ),
            ("returns a dict", lambda: type(deep_merge(*make_merge_inputs())).__name__, "dict"),
            ("inputs untouched, nothing shared", merge_shares_nothing, True),
            ("empty override", lambda: deep_merge({"a": {"b": 1}}, {}), {"a": {"b": 1}}),
            ("empty base", lambda: deep_merge({}, {"a": [1]}), {"a": [1]}),
            (
                "dict replaces scalar",
                lambda: deep_merge({"a": 1}, {"a": {"b": 2}}),
                {"a": {"b": 2}},
            ),
            ("scalar replaces dict", lambda: deep_merge({"a": {"b": 2}}, {"a": None}), {"a": None}),
            (
                "three levels deep",
                lambda: deep_merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 3}}}),
                {"a": {"b": {"c": 1, "d": 3}}},
            ),
        ]
    )
    print("Exercise 2 — snapshot, discount, diff")
    expected_changes = [
        PriceChange(1001, "TEA-500G", Decimal("249.00"), Decimal("224.10")),
        PriceChange(1002, "RICE-5KG", Decimal("525.50"), Decimal("499.23")),
    ]
    run_checks(
        [
            (
                "diff of identical orders",
                lambda: diff_orders(make_sample_orders(), make_sample_orders()),
                [],
            ),
            (
                "discount_and_diff changes",
                lambda: discount_and_diff(make_sample_orders(), SAMPLE_DISCOUNTS),
                expected_changes,
            ),
            (
                "orders were discounted in place",
                lambda: orders_after_discount()[0]["lines"][0]["unit_price"],
                Decimal("224.10"),
            ),
            ("no discounts, no changes", lambda: discount_and_diff(make_sample_orders(), {}), []),
            (
                "diff after a manual edit",
                lambda: diff_orders(make_sample_orders(), orders_with_rice_at_one_rupee()),
                [PriceChange(1002, "RICE-5KG", Decimal("525.50"), Decimal("1.00"))],
            ),
        ]
    )


# Lab 1.8 -------------------------------------------------------------------------------------


def parse_command(command_text: str) -> tuple[Any, ...]:
    """Parse a cart command into a tuple, using match."""
    match command_text.split():
        case ["add", sku]:
            return ("add", sku, 1)
        case ["add", sku, quantity_text] if quantity_text.isdigit() and int(quantity_text) > 0:
            return ("add", sku, int(quantity_text))
        case ["add", _, _]:
            return ("error", "quantity must be a positive integer")
        case ["remove", sku]:
            return ("remove", sku)
        case ["list" | "ls"]:
            return ("list",)
        case ["checkout"]:
            return ("checkout",)
        case ["quit" | "exit"]:
            return ("quit",)
        case []:
            return ("error", "empty command")
        case [unknown_command, *_]:
            return ("error", f"unknown command: {unknown_command}")


def fizzbuzz(number: int) -> str:
    """Return the FizzBuzz word for number, using match on a tuple of remainders."""
    match (number % 3, number % 5):
        case (0, 0):
            return "FizzBuzz"
        case (0, _):
            return "Fizz"
        case (_, 0):
            return "Buzz"
        case _:
            return str(number)


def find_first_duplicate(items: Iterable[Hashable]) -> Hashable | None:
    """Return the first item seen twice, or None, using for ... else."""
    seen_items: set[Hashable] = set()
    for item in items:
        if item in seen_items:
            duplicate = item
            break
        seen_items.add(item)
    else:
        duplicate = None
    return duplicate


def check_lab_1_8() -> None:
    """Run the same checks as the Lab 1.8 check cells in the notebook."""
    print("Exercise 1 — parse_command")
    run_checks(
        [
            (
                "add default quantity",
                lambda: parse_command("add TEA-500G"),
                ("add", "TEA-500G", 1),
            ),
            ("add with quantity", lambda: parse_command("add RICE-5KG 3"), ("add", "RICE-5KG", 3)),
            ("extra spaces", lambda: parse_command("  add   GHEE-1L   2 "), ("add", "GHEE-1L", 2)),
            (
                "bad quantity",
                lambda: parse_command("add TEA-500G two"),
                ("error", "quantity must be a positive integer"),
            ),
            (
                "zero quantity",
                lambda: parse_command("add TEA-500G 0"),
                ("error", "quantity must be a positive integer"),
            ),
            ("remove", lambda: parse_command("remove TEA-500G"), ("remove", "TEA-500G")),
            ("list", lambda: parse_command("list"), ("list",)),
            ("ls alias", lambda: parse_command("ls"), ("list",)),
            ("checkout", lambda: parse_command("checkout"), ("checkout",)),
            ("quit", lambda: parse_command("quit"), ("quit",)),
            ("exit alias", lambda: parse_command("exit"), ("quit",)),
            ("blank", lambda: parse_command("   "), ("error", "empty command")),
            ("unknown", lambda: parse_command("dance now"), ("error", "unknown command: dance")),
            (
                "remove without sku",
                lambda: parse_command("remove"),
                ("error", "unknown command: remove"),
            ),
        ]
    )
    print("Exercise 2 — fizzbuzz")
    run_checks(
        [
            ("1", lambda: fizzbuzz(1), "1"),
            ("3", lambda: fizzbuzz(3), "Fizz"),
            ("5", lambda: fizzbuzz(5), "Buzz"),
            ("15", lambda: fizzbuzz(15), "FizzBuzz"),
            ("0 is a multiple of 15", lambda: fizzbuzz(0), "FizzBuzz"),
            (
                "1 to 15",
                lambda: " ".join(fizzbuzz(number) for number in range(1, 16)),
                "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz",
            ),
        ]
    )
    print("Exercise 3 — find_first_duplicate")
    run_checks(
        [
            ("second occurrence wins", lambda: find_first_duplicate([3, 1, 4, 1, 3]), 1),
            ("adjacent", lambda: find_first_duplicate(["a", "a"]), "a"),
            ("no duplicate", lambda: find_first_duplicate([1, 2, 3]), None),
            ("empty", lambda: find_first_duplicate([]), None),
            ("string iterable", lambda: find_first_duplicate("python"), None),
            ("generator", lambda: find_first_duplicate(n % 4 for n in range(10)), 0),
            ("1 and True are equal", lambda: find_first_duplicate([1, True]), True),
        ]
    )


# Lab 1.9 -------------------------------------------------------------------------------------


def read_in_chunks(stream: IO[Any], size: int) -> Iterator[Any]:
    """Return an iterator of chunks of at most size items from stream."""
    if size < 1:
        raise ValueError(f"size must be at least 1, got {size}")
    end_of_stream = stream.read(0)  # "" for text streams, b"" for binary streams
    return iter(lambda: stream.read(size), end_of_stream)


def numbered_lines_unpythonic(lines: list[str]) -> list[str]:
    """Number lines from 1."""
    result = []
    for index in range(len(lines)):
        result.append(f"{index + 1}. {lines[index]}")
    return result


def line_totals_unpythonic(unit_prices: list[int], quantities: list[int]) -> list[int]:
    """Multiply parallel lists."""
    totals = []
    for index in range(len(unit_prices)):
        totals.append(unit_prices[index] * quantities[index])
    return totals


def has_overdue_unpythonic(days_overdue: list[int]) -> bool:
    """Return True if any invoice is more than 30 days overdue."""
    found = False
    for days in days_overdue:
        if days > 30:
            found = True
            break
    return found


def count_statuses_unpythonic(statuses: list[str]) -> dict[str, int]:
    """Count how often each status occurs."""
    counts = {}
    for status in statuses:
        if status in counts:
            counts[status] = counts[status] + 1
        else:
            counts[status] = 1
    return counts


def even_squares_unpythonic(numbers: list[int]) -> list[int]:
    """Square the even numbers."""
    squares = []
    for number in numbers:
        if number % 2 == 0:
            squares.append(number * number)
    return squares


def numbered_lines(lines: list[str]) -> list[str]:
    """Number lines from 1 (enumerate)."""
    return [f"{line_number}. {line}" for line_number, line in enumerate(lines, start=1)]


def line_totals(unit_prices: list[int], quantities: list[int]) -> list[int]:
    """Multiply parallel lists (zip, strict)."""
    return [price * quantity for price, quantity in zip(unit_prices, quantities, strict=True)]


def has_overdue(days_overdue: list[int]) -> bool:
    """Return True if any invoice is more than 30 days overdue (any)."""
    return any(days > 30 for days in days_overdue)


def count_statuses(statuses: list[str]) -> dict[str, int]:
    """Count how often each status occurs (Counter)."""
    return dict(Counter(statuses))


def even_squares(numbers: list[int]) -> list[int]:
    """Square the even numbers (comprehension)."""
    return [number * number for number in numbers if number % 2 == 0]


class WebhookEvent(NamedTuple):
    """One webhook delivery from a payment provider (amount in paise)."""

    event_id: str
    event_type: str
    amount: int
    received_at: dt.datetime


SAMPLE_WEBHOOK_EVENTS = [
    WebhookEvent("evt_3", "payment.captured", 49_900, dt.datetime(2026, 11, 3, 10, 5)),
    WebhookEvent("evt_1", "payment.captured", 129_900, dt.datetime(2026, 11, 3, 9, 15)),
    WebhookEvent("evt_4", "refund.created", 19_900, dt.datetime(2026, 11, 3, 11, 0)),
    WebhookEvent("evt_2", "payment.failed", 129_900, dt.datetime(2026, 11, 3, 9, 40)),
    WebhookEvent("evt_5", "payment.captured", 9_900, dt.datetime(2026, 11, 3, 8, 55)),
]


def summarize_webhooks(events: list[WebhookEvent]) -> dict[str, object]:
    """Summarize webhook events with sum, max and sorted."""
    largest_event = max(events, key=lambda event: event.amount, default=None)
    return {
        "event_count": len(events),
        "captured_total": sum(
            event.amount for event in events if event.event_type == "payment.captured"
        ),
        "largest_event_id": None if largest_event is None else largest_event.event_id,
        "ids_by_time": [
            event.event_id for event in sorted(events, key=lambda event: event.received_at)
        ],
        "event_types": sorted({event.event_type for event in events}),
    }


def reads_lazily() -> list[int]:
    """Return the stream positions before and after the first next()."""
    lazy_stream = io.StringIO("abcdefgh")
    chunk_iterator = read_in_chunks(lazy_stream, 3)
    position_before = lazy_stream.tell()
    next(chunk_iterator)
    return [position_before, lazy_stream.tell()]


def returns_an_iterator() -> bool:
    """Return True if read_in_chunks returns an iterator (iter(x) is x)."""
    chunk_iterator = read_in_chunks(io.StringIO("x"), 1)
    return iter(chunk_iterator) is chunk_iterator


def check_lab_1_9() -> None:
    """Run the same checks as the Lab 1.9 check cells in the notebook."""
    print("Exercise 1 — read_in_chunks")
    run_checks(
        [
            (
                "text chunks",
                lambda: list(read_in_chunks(io.StringIO("abcdefgh"), 3)),
                ["abc", "def", "gh"],
            ),
            (
                "binary chunks",
                lambda: list(read_in_chunks(io.BytesIO(b"\x00\x01\x02\x03"), 2)),
                [b"\x00\x01", b"\x02\x03"],
            ),
            ("empty stream", lambda: list(read_in_chunks(io.StringIO(""), 4)), []),
            (
                "size larger than data",
                lambda: list(read_in_chunks(io.BytesIO(b"hi"), 100)),
                [b"hi"],
            ),
            ("returns an iterator", returns_an_iterator, True),
            ("reads lazily", reads_lazily, [0, 3]),
            (
                "size 0 raises",
                lambda: raised_error_name(lambda: read_in_chunks(io.StringIO("x"), 0)),
                "ValueError",
            ),
        ]
    )
    print("Exercise 2 — five idiomatic rewrites")
    sample_lines = ["GET /", "POST /cart"]
    sample_statuses = ["paid", "failed", "paid", "refunded", "paid"]
    run_checks(
        [
            (
                "numbered_lines",
                lambda: numbered_lines(sample_lines),
                numbered_lines_unpythonic(sample_lines),
            ),
            ("numbered_lines empty", lambda: numbered_lines([]), []),
            (
                "line_totals",
                lambda: line_totals([249, 640], [2, 1]),
                line_totals_unpythonic([249, 640], [2, 1]),
            ),
            (
                "line_totals strict",
                lambda: raised_error_name(lambda: line_totals([249, 640], [2])),
                "ValueError",
            ),
            ("has_overdue true", lambda: has_overdue([3, 45]), has_overdue_unpythonic([3, 45])),
            ("has_overdue false", lambda: has_overdue([30, 0]), False),
            ("has_overdue empty", lambda: has_overdue([]), False),
            (
                "count_statuses",
                lambda: count_statuses(sample_statuses),
                count_statuses_unpythonic(sample_statuses),
            ),
            ("count_statuses empty", lambda: count_statuses([]), {}),
            (
                "even_squares",
                lambda: even_squares([1, 2, 3, 4, -6]),
                even_squares_unpythonic([1, 2, 3, 4, -6]),
            ),
        ]
    )
    print("Exercise 3 — summarize_webhooks")
    run_checks(
        [
            (
                "sample summary",
                lambda: summarize_webhooks(SAMPLE_WEBHOOK_EVENTS),
                {
                    "event_count": 5,
                    "captured_total": 189_700,
                    "largest_event_id": "evt_1",
                    "ids_by_time": ["evt_5", "evt_1", "evt_2", "evt_3", "evt_4"],
                    "event_types": ["payment.captured", "payment.failed", "refund.created"],
                },
            ),
            (
                "no events",
                lambda: summarize_webhooks([]),
                {
                    "event_count": 0,
                    "captured_total": 0,
                    "largest_event_id": None,
                    "ids_by_time": [],
                    "event_types": [],
                },
            ),
            (
                "no captures",
                lambda: summarize_webhooks(SAMPLE_WEBHOOK_EVENTS[2:4])["captured_total"],
                0,
            ),
        ]
    )


# Lab 1.10 ------------------------------------------------------------------------------------


MAX_PAGE_SIZE = 100


def build_query_string(
    base_url: str, /, *, page: int = 1, page_size: int = 20, **filters: object
) -> str:
    """Return base_url with page, page_size and the non-None filters as a query string."""
    if page < 1:
        raise ValueError(f"page must be at least 1, got {page}")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}, got {page_size}")
    query_pairs = [
        ("page", page),
        ("page_size", page_size),
        *((name, value) for name, value in filters.items() if value is not None),
    ]
    return f"{base_url}?{urlencode(query_pairs)}"


def apply_pipeline(value: Any, *transforms: Callable[[Any], Any]) -> Any:
    """Return value passed through every transform, left to right."""
    for transform in transforms:
        value = transform(value)
    return value


OPERATIONS: dict[str, Callable[[float, float], float]] = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
    "floor_divide": operator.floordiv,
    "modulo": operator.mod,
    "power": operator.pow,
}


def calculate(operation_name: str, left: float, right: float) -> float:
    """Apply the named operation from OPERATIONS to left and right."""
    operation = OPERATIONS.get(operation_name)
    if operation is None:
        raise ValueError(f"unknown operation: {operation_name}")
    return operation(left, right)


def check_lab_1_10() -> None:
    """Run the same checks as the Lab 1.10 check cells in the notebook."""
    print("Exercise 1 — build_query_string")
    run_checks(
        [
            (
                "defaults",
                lambda: build_query_string("/api/products"),
                "/api/products?page=1&page_size=20",
            ),
            (
                "filters in call order",
                lambda: build_query_string("/api/products", page=2, category="tea", max_price=500),
                "/api/products?page=2&page_size=20&category=tea&max_price=500",
            ),
            (
                "None filters skipped",
                lambda: build_query_string("/search", q="masala chai", city=None),
                "/search?page=1&page_size=20&q=masala+chai",
            ),
            (
                "filter named base_url",
                lambda: build_query_string("/api", base_url="mirror"),
                "/api?page=1&page_size=20&base_url=mirror",
            ),
            (
                "page is keyword-only",
                lambda: raised_error_name(lambda: build_query_string("/api", 2)),
                "TypeError",
            ),
            (
                "page 0",
                lambda: raised_error_name(lambda: build_query_string("/api", page=0)),
                "ValueError",
            ),
            (
                "page_size 101",
                lambda: raised_error_name(lambda: build_query_string("/api", page_size=101)),
                "ValueError",
            ),
            (
                "parameter kinds",
                lambda: [
                    parameter.kind.name
                    for parameter in inspect.signature(build_query_string).parameters.values()
                ],
                ["POSITIONAL_ONLY", "KEYWORD_ONLY", "KEYWORD_ONLY", "VAR_KEYWORD"],
            ),
        ]
    )
    print("Exercise 2 — apply_pipeline")
    slug_steps = [str.strip, str.lower, lambda text: text.replace(" ", "-")]
    original_list = [3, 1, 2]
    run_checks(
        [
            (
                "slug pipeline",
                lambda: apply_pipeline("  Masala Chai ", *slug_steps),
                "masala-chai",
            ),
            ("numbers", lambda: apply_pipeline(10, lambda n: n + 5, lambda n: n * 2), 30),
            ("order matters", lambda: apply_pipeline(10, lambda n: n * 2, lambda n: n + 5), 25),
            (
                "no transforms returns the same object",
                lambda: apply_pipeline(original_list) is original_list,
                True,
            ),
            (
                "built-ins as transforms",
                lambda: apply_pipeline([3, 1, 2], sorted, tuple),
                (1, 2, 3),
            ),
            ("types can change", lambda: apply_pipeline("42", int, float, str), "42.0"),
        ]
    )
    print("Exercise 3 — calculate")
    run_checks(
        [
            ("add", lambda: calculate("add", 2, 3), 5),
            ("subtract", lambda: calculate("subtract", 2, 3), -1),
            ("multiply", lambda: calculate("multiply", 249, 2), 498),
            ("divide", lambda: calculate("divide", 7, 2), 3.5),
            ("floor_divide", lambda: calculate("floor_divide", -7, 2), -4),
            ("modulo", lambda: calculate("modulo", -7, 3), 2),
            ("power", lambda: calculate("power", 2, 10), 1024),
            (
                "divide by zero",
                lambda: raised_error_name(lambda: calculate("divide", 1, 0)),
                "ZeroDivisionError",
            ),
            (
                "unknown operation",
                lambda: raised_error_name(lambda: calculate("sqrt", 9, 0)),
                "ValueError",
            ),
            (
                "table has the seven names",
                lambda: sorted(OPERATIONS),
                ["add", "divide", "floor_divide", "modulo", "multiply", "power", "subtract"],
            ),
            (
                "table uses operator functions",
                lambda: OPERATIONS.get("add") is operator.add,
                True,
            ),
        ]
    )


if __name__ == "__main__":
    for lab_title, check_lab in [
        ("Lab 1.3", check_lab_1_3),
        ("Lab 1.4", check_lab_1_4),
        ("Lab 1.5", check_lab_1_5),
        ("Lab 1.6", check_lab_1_6),
        ("Lab 1.7", check_lab_1_7),
        ("Lab 1.8", check_lab_1_8),
        ("Lab 1.9", check_lab_1_9),
        ("Lab 1.10", check_lab_1_10),
    ]:
        print(f"\n=== {lab_title} ===")
        check_lab()
