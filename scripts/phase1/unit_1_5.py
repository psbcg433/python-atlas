"""Unit 1.5 — Collection Data Types I: Lists, Tuples and Ranges (with Lab 1.5)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import array
import csv
import dis
import io
import operator
import sqlite3
import sys
import timeit
from collections import namedtuple
from collections.abc import Callable, Hashable, Iterable
from typing import Any, NamedTuple


def show_size(label: str, obj: object) -> None:
    """Print the shallow size in bytes, the type and the id of an object."""
    print(f"{label}: {sys.getsizeof(obj)} bytes, type={type(obj).__name__}, id={id(obj)}")


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised, or "no error"."""
    try:
        thunk()
    except Exception as error:
        return type(error).__name__
    return "no error"


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener, setup and 1.5.1."""
    return [
        md(
            """
            ## Unit 1.5 — Collection Data Types I: Lists, Tuples and Ranges

            **Objectives**

            - Use the operations every sequence shares, and know which types support which.
            - Explain how a `list` is stored, and the cost of each list operation.
            - Use the complete `list` API, slice assignment and starred unpacking.
            - Sort by several keys, stably, in mixed directions.
            - Choose between `list`, `tuple`, named tuples, `range` and `array.array`.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `arr.push(x)` / `arr.pop()` | `items.append(x)` / `items.pop()` | `append` returns `None`, not the new length |
            | `arr.shift()` / `arr.unshift(x)` | `items.pop(0)` / `items.insert(0, x)` | O(n): use `collections.deque` (1.6.7) for queues |
            | `[10, 9, 1].sort()` → `[1, 10, 9]` | `sorted([10, 9, 1])` → `[1, 9, 10]` | Python compares values; mixing `int` and `str` raises `TypeError` |
            | `arr.sort()` returns the array | `items.sort()` returns `None` | Use `sorted(items)` when you want a new list |
            | `arr.slice(1, 3)`, `arr.at(-1)` | `items[1:3]`, `items[-1]` | Slices also take a step, and assigning to a slice replaces it |
            | `Object.freeze([lat, lng])` | `(lat, lng)` tuple | A tuple is hashable, so it can be a dict key |
            | `const [first, ...rest] = arr` | `first, *rest = items` | Works on any iterable, and the star can sit in the middle |
            | `Array.from({length: 5}, (_, i) => i)` | `range(5)` | `range` is lazy: no list is built |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
        md(
            """
            ### 1.5.1 Common sequence operations

            Every sequence type supports indexing, slicing, `in`, `len`, `min`, `max`, `count` and
            `index`; most also support `+` (concatenate) and `*` (repeat). `index(x, start)`
            starts searching at `start`.
            """
        ),
        code(
            """
            weekly_orders = [12, 7, 19, 7, 25]
            print(f"{weekly_orders[0]=}, {weekly_orders[-1]=}, {weekly_orders[1:4]=}")
            print(f"{weekly_orders[::-1]=}, {19 in weekly_orders=}, {len(weekly_orders)=}")
            print(f"{weekly_orders + [30]=}, {[0] * 3=}")
            print(f"{min(weekly_orders)=}, {max(weekly_orders)=}")
            print(f"{weekly_orders.count(7)=}, {weekly_orders.index(7)=}, {weekly_orders.index(7, 2)=}")
            """
        ),
        md(
            """
            **Support table.** The same operations across five sequence types (✓ supported,
            ✗ raises `TypeError`):

            | Operation | `list` | `tuple` | `str` | `range` | `bytes` |
            | --- | --- | --- | --- | --- | --- |
            | `s[i]` | ✓ | ✓ | ✓ | ✓ | ✓ (gives `int`) |
            | `s[a:b]` | ✓ | ✓ | ✓ | ✓ (gives `range`) | ✓ |
            | `x in s` | ✓ | ✓ | ✓ (substring) | ✓ (O(1) for ints) | ✓ |
            | `len(s)` | ✓ | ✓ | ✓ | ✓ | ✓ |
            | `s + t` | ✓ | ✓ | ✓ | ✗ | ✓ |
            | `s * n` | ✓ | ✓ | ✓ | ✗ | ✓ |
            | `min(s)`, `max(s)` | ✓ | ✓ | ✓ | ✓ | ✓ |
            | `s.count(x)` | ✓ | ✓ | ✓ | ✓ | ✓ |
            | `s.index(x)` | ✓ | ✓ | ✓ | ✓ | ✓ |
            | `s[i] = x` | ✓ | ✗ | ✗ | ✗ | ✗ (use `bytearray`) |

            The next cell checks every row of the table by running the operation on each type.
            """
        ),
        code(
            '''
            def supports(operation: Callable[[Any], object], sequence: Any) -> bool:
                """Return True if operation(sequence) runs without TypeError."""
                try:
                    operation(sequence)
                except TypeError:
                    return False
                return True


            def assign_first(sequence: Any) -> None:
                """Try to replace the first item in place."""
                sequence[0] = sequence[0]


            sequence_samples = {
                "list": [3, 1, 2],
                "tuple": (3, 1, 2),
                "str": "312",
                "range": range(3),
                "bytes": b"312",
            }
            sequence_operations: dict[str, Callable[[Any], object]] = {
                "s[i]": lambda sequence: sequence[0],
                "s[a:b]": lambda sequence: sequence[1:],
                "x in s": lambda sequence: sequence[0] in sequence,
                "len(s)": len,
                "s + t": lambda sequence: sequence + sequence,
                "s * n": lambda sequence: sequence * 2,
                "min, max": lambda sequence: (min(sequence), max(sequence)),
                "s.count(x)": lambda sequence: sequence.count(sequence[0]),
                "s.index(x)": lambda sequence: sequence.index(sequence[0]),
                "s[i] = x": assign_first,
            }
            print(f"{'operation':<12}" + "".join(f"{type_name:>7}" for type_name in sequence_samples))
            for operation_label, operation in sequence_operations.items():
                support_marks = [
                    "✓" if supports(operation, sample) else "✗" for sample in sequence_samples.values()
                ]
                print(f"{operation_label:<12}" + "".join(f"{mark:>7}" for mark in support_marks))
            '''
        ),
    ]


def _list_internals_cells() -> list[NotebookNode]:
    """1.5.2 Lists — internals."""
    return [
        md(
            """
            ### 1.5.2 Lists (`list`) — internals

            A CPython `list` is a **dynamic array of pointers**. The list object holds its length,
            its capacity (`allocated`) and a pointer to a separate array of `PyObject*` slots;
            each slot points to an item object stored elsewhere. Items are never stored inline,
            which is why one list can hold any mix of types.

            ```mermaid
            flowchart LR
                header["list object<br/>ob_size = 3<br/>allocated = 4"] --> slots["pointer array<br/>slot 0 | slot 1 | slot 2 | (spare)"]
                slots --> item_int["int 10"]
                slots --> item_str["str 'dosa'"]
                slots --> item_float["float 2.5"]
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            list object                pointer array (capacity 4)
            +----------------+        +--------+--------+--------+--------+
            | ob_size = 3    |  --->  | slot 0 | slot 1 | slot 2 | spare  |
            | allocated = 4  |        +---|----+---|----+---|----+--------+
            +----------------+            v        v        v
                                       int 10  str 'dosa' float 2.5
            ```

            </details>

            When the array is full, `append` **over-allocates**: it grows by roughly 1/8 plus a
            few slots, so most appends just fill a spare slot. That is why `append` is O(1)
            *amortized*. `sys.getsizeof` measures the list and its slot array, not the items.
            """
        ),
        code(
            """
            growing_list: list[int] = []
            previous_size = sys.getsizeof(growing_list)
            print(f"len=0    size={previous_size} bytes")
            for item_count in range(1, 41):
                growing_list.append(item_count)
                current_size = sys.getsizeof(growing_list)
                if current_size != previous_size:
                    added_slots = (current_size - previous_size) // 8
                    print(f"len={item_count:<4} size={current_size} bytes (+{added_slots} slots)")
                    previous_size = current_size
            print(f"{sys.getsizeof([1]) == sys.getsizeof([10**1000])=}  (items are not counted)")
            """
        ),
        md(
            """
            **Cost of list operations** (*n* = length of the list, *k* = length of the other
            iterable or slice):

            | Operation | Cost | Why |
            | --- | --- | --- |
            | `items[i]`, `items[i] = x` | O(1) | pointer arithmetic |
            | `append(x)`, `pop()` | O(1) amortized | work at the end only |
            | `pop(0)`, `insert(0, x)` | O(n) | every pointer shifts by one slot |
            | `x in items`, `index(x)`, `remove(x)` | O(n) | linear scan comparing with `==` |
            | `extend(other)`, `items[a:b]` | O(k) | copy *k* pointers |
            | `sort()`, `sorted()` | O(n log n) | Timsort (O(n) when already sorted) |

            The timings make the table concrete. Absolute numbers depend on the machine; the gaps
            between rows are what matter.
            """
        ),
        code(
            """
            timing_cases = [
                ("items[50_000]", "O(1)"),
                ("items.append(0); items.pop()", "O(1)"),
                ("items.insert(0, 0); items.pop(0)", "O(n)"),
                ("99_999 in items", "O(n)"),
            ]
            run_count = 1_000
            for statement, complexity in timing_cases:
                elapsed_seconds = timeit.timeit(
                    statement, setup="items = list(range(100_000))", number=run_count
                )
                nanoseconds_per_run = elapsed_seconds / run_count * 1e9
                print(f"{statement:<34} {complexity:<5} {nanoseconds_per_run:>12,.0f} ns per run")
            """
        ),
    ]


def _list_methods_cells() -> list[NotebookNode]:
    """1.5.3 List methods."""
    return [
        md(
            """
            ### 1.5.3 List methods (complete API)

            **Adding.** `append` adds one object (even a list, which becomes a nested item);
            `extend` adds every item of any iterable; `insert(i, x)` puts `x` before index `i`.
            `items += iterable` is `extend`: it changes the list **in place**. `items + other`
            builds a **new** list and requires `other` to be a list. Mutating methods return
            `None`.
            """
        ),
        code(
            """
            cart_items = ["idli"]
            cart_items.append("dosa")
            cart_items.extend(["vada", "chutney"])
            cart_items.insert(1, "coffee")
            print(f"{cart_items=}")
            print(f"{cart_items.append('tea')=}  (mutating methods return None)")
            nested_cart = ["idli"]
            nested_cart.append(["vada", "chutney"])
            print(f"{nested_cart=}  (append adds the list as one item)")
            original_cart = cart_items
            cart_items += ("sambar",)
            print(f"{cart_items is original_cart=}  (+= extends in place, accepts any iterable)")
            cart_items = cart_items + ["payasam"]
            print(f"{cart_items is original_cart=}  (+ builds a new list)")
            print(f"list + tuple: {raised_error_name(lambda: ['idli'] + ('vada',))}")
            """
        ),
        md(
            """
            **Removing.** `remove(x)` deletes the **first** item equal to `x` and raises
            `ValueError` if there is none. `pop(i)` removes and returns the item at `i` (default:
            the last one). `clear()` empties the list. `del items[i]` and `del items[a:b]` delete
            by position without returning anything.
            """
        ),
        code(
            """
            order_queue = ["idli", "dosa", "vada", "dosa", "upma", "poha", "khichdi"]
            order_queue.remove("dosa")
            print(f"{order_queue=}  (only the first 'dosa' is gone)")
            try:
                order_queue.remove("pizza")
            except ValueError as error:
                print(f"remove: {type(error).__name__}: {error}")
            last_order = order_queue.pop()
            second_order = order_queue.pop(1)
            print(f"{last_order=}, {second_order=}, {order_queue=}")
            del order_queue[0]
            print(f"after del [0]: {order_queue}")
            del order_queue[1:3]
            print(f"after del [1:3]: {order_queue}")
            order_queue.clear()
            print(f"after clear(): {order_queue}, pop on empty: {raised_error_name(order_queue.pop)}")
            """
        ),
        md(
            """
            **Searching.** `index(x, start, end)` returns the first position of `x` within
            `items[start:end]` (positions are still counted from the start of the list). `count`
            counts equal items. Both compare with `==`, as does `in`.
            """
        ),
        code(
            """
            daily_statuses = ["ok", "late", "ok", "failed", "late", "ok"]
            print(f"{daily_statuses.index('late')=}")
            print(f"{daily_statuses.index('late', 2)=}  (search from position 2)")
            print(f"{daily_statuses.index('ok', 3, 6)=}")
            print(f"index outside the window: {raised_error_name(lambda: daily_statuses.index('failed', 4))}")
            print(f"{daily_statuses.count('ok')=}, {'failed' in daily_statuses=}")
            print(f"{[1, 1.0, True].count(1)=}  (1 == 1.0 == True)")
            """
        ),
        md(
            """
            **Ordering.** `items.sort()` sorts **in place** and returns `None`; `sorted(iterable)`
            returns a new list and works on any iterable. Both take `key=` and `reverse=`.
            Likewise `items.reverse()` reverses in place, while `reversed(items)` returns a lazy
            iterator.
            """
        ),
        code(
            """
            dish_names = ["vada", "Idli", "dosa", "Upma"]
            sorted_copy = sorted(dish_names)
            print(f"{sorted_copy=}, {dish_names=}  (original untouched)")
            print(f"{dish_names.sort(key=str.lower)=}  (sort() returns None)")
            print(f"{dish_names=}  (sorted in place, case-insensitive)")
            print(f"{sorted(dish_names, key=len, reverse=True)=}")
            dish_names.reverse()
            print(f"{dish_names=}  (reversed in place)")
            backwards_iterator = reversed(dish_names)
            print(f"{type(backwards_iterator).__name__=}, {list(backwards_iterator)=}")
            print(f"{sorted('dosa')=}, {sorted({3, 1, 2})=}  (any iterable)")
            """
        ),
        md(
            """
            **Copying.** `items.copy()`, `items[:]` and `list(items)` all make a **shallow** copy:
            a new list holding the *same* item objects. Changing the new list does not affect the
            old one, but mutating a shared inner object shows up in both. Unit 1.7 covers deep
            copies.
            """
        ),
        code(
            """
            menu_rows = [["idli", 40], ["dosa", 60]]
            copy_by_method = menu_rows.copy()
            copy_by_slice = menu_rows[:]
            copy_by_constructor = list(menu_rows)
            print(f"{copy_by_method is menu_rows=}, {copy_by_slice == menu_rows=}")
            copy_by_method.append(["vada", 30])
            print(f"{len(menu_rows)=}, {len(copy_by_method)=}  (outer lists are independent)")
            copy_by_constructor[0][1] = 45
            print(f"{menu_rows[0]=}  (inner lists are shared: the original changed too)")
            print(f"{copy_by_slice[0] is menu_rows[0]=}")
            """
        ),
        md(
            """
            **Slice assignment** replaces a slice with the items of any iterable, and the lengths
            may differ, so the list can grow or shrink. An empty slice `items[i:i]` inserts.
            **Extended slices** (with a step) need exactly as many items as they select.
            **Starred unpacking** collects "the rest" into a list.
            """
        ),
        code(
            """
            seat_row = ["A1", "A2", "A3", "A4", "A5"]
            seat_row[1:3] = ["B2"]
            print(f"{seat_row=}  (two items replaced by one)")
            seat_row[1:1] = ["NEW1", "NEW2"]
            print(f"{seat_row=}  (empty slice: pure insert)")
            seat_row[::2] = ["x", "y", "z"]
            print(f"{seat_row=}  (extended slice, same length)")
            try:
                seat_row[::2] = ["only one"]
            except ValueError as error:
                print(f"{type(error).__name__}: {error}")
            first_seat, *other_seats = seat_row
            *_, last_seat = seat_row
            front_seat, *middle_seats, back_seat = seat_row
            print(f"{first_seat=}, {other_seats=}, {last_seat=}")
            print(f"{front_seat=}, {middle_seats=}, {back_seat=}")
            """
        ),
    ]


def _sorting_cells() -> list[NotebookNode]:
    """1.5.4 Sorting in depth."""
    return [
        md(
            """
            ### 1.5.4 Sorting in depth

            Python sorts with **Timsort**, a merge sort that finds existing ordered runs, so
            nearly sorted data costs close to O(n). (Since 3.11 CPython merges runs with the
            *powersort* strategy.) The sort is **stable**: items with equal keys keep their
            original relative order.

            Stability enables **multi-pass sorting**: sort by the least important key first, then
            by more important keys. Each pass keeps the order the earlier passes produced among
            ties.
            """
        ),
        code(
            """
            customer_orders = [("Ravi", "Pune"), ("Asha", "Delhi"), ("Meena", "Pune"), ("John", "Delhi")]
            print(f"{sorted(customer_orders, key=lambda order: order[1])=}")
            print("  ^ within each city the original order (Ravi before Meena) is kept")
            by_name = sorted(customer_orders, key=lambda order: order[0])
            by_city_then_name = sorted(by_name, key=lambda order: order[1])
            print(f"{by_city_then_name=}")
            """
        ),
        md(
            """
            **Key functions.** `key` is called once per item, and items are compared by the key's
            result:

            - `key=str.lower` for case-insensitive order.
            - `operator.itemgetter(1)` reads `item[1]`; `itemgetter(2, 0)` returns a tuple of both.
            - `operator.attrgetter("price")` reads `item.price` (works on any object with
              attributes).
            - **Tuple keys** compare element by element. For mixed directions, negate numeric
              parts: `key=lambda p: (-p.rating, p.price)` means rating descending, price ascending.
              Strings cannot be negated, so use multi-pass sorting with `reverse=True` for them.

            The products below use `NamedTuple`, covered in 1.5.6; here it is just a record with
            attributes.
            """
        ),
        code(
            '''
            class Product(NamedTuple):
                """A product in a catalogue."""

                name: str
                price: int
                rating: float


            catalogue = [
                Product("pen", 20, 4.2),
                Product("Notebook", 60, 4.8),
                Product("eraser", 5, 4.2),
                Product("Bag", 900, 4.8),
            ]
            print(f"{sorted(['pen', 'Notebook', 'eraser'])=}")
            print(f"{sorted(['pen', 'Notebook', 'eraser'], key=str.lower)=}")
            print([product.name for product in sorted(catalogue, key=operator.itemgetter(1))])
            print(sorted(catalogue, key=operator.itemgetter(2, 0))[:2])
            print([product.name for product in sorted(catalogue, key=operator.attrgetter("rating"))])
            best_then_cheapest = sorted(catalogue, key=lambda product: (-product.rating, product.price))
            print([(product.name, product.rating, product.price) for product in best_then_cheapest])
            '''
        ),
        md(
            """
            **JS bridge.** JavaScript's default `sort()` converts items to strings, so
            `[10, 9, 1, 100].sort()` gives `[1, 10, 100, 9]`. Python compares the values
            themselves, and refuses to compare unrelated types instead of guessing.
            """
        ),
        code(
            """
            print(f"{sorted([10, 9, 1, 100])=}")
            print(f"{sorted(['10', '9', '1', '100'])=}  (what JS does to numbers)")
            try:
                sorted([3, "2", 1])
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{sorted([3, '2', 1], key=str)=}  (an explicit key makes it work)")
            """
        ),
    ]


def _tuple_cells() -> list[NotebookNode]:
    """1.5.5 Tuples."""
    return [
        md(
            """
            ### 1.5.5 Tuples (`tuple`)

            **The comma makes the tuple**, not the parentheses: `(42)` is just the int 42, while
            `42,` and `(42,)` are one-item tuples. `()` is the empty tuple. Writing several values
            separated by commas **packs** them; assigning a tuple to several names **unpacks** it.
            Unpacking can be nested and starred, and `a, b = b, a` swaps without a temporary.

            > **Note:** the two `# fmt: skip` comments stop the formatter from rewriting `(42)`
            > as `42` and `42,` as `(42,)`, which would hide the point.
            """
        ),
        code(
            """
            not_a_tuple = (42)  # fmt: skip
            one_item_tuple = 42,  # fmt: skip
            also_one_item = (42,)
            empty_tuple = ()
            print(f"{type(not_a_tuple).__name__=}, {one_item_tuple=}, {also_one_item=}, {empty_tuple=}")
            office_location = 12.97, 77.59
            latitude, longitude = office_location
            print(f"{office_location=}, {latitude=}, {longitude=}")
            city_name, (city_latitude, city_longitude) = ("Bengaluru", (12.97, 77.59))
            print(f"{city_name=}, {city_latitude=}, {city_longitude=}")
            top_scorer, *other_scorers = ("Asha", "Ravi", "Meena")
            print(f"{top_scorer=}, {other_scorers=}  (the starred name is always a list)")
            home_team, away_team = "India", "Australia"
            home_team, away_team = away_team, home_team
            print(f"{home_team=}, {away_team=}")
            """
        ),
        md(
            """
            **Methods and hashing.** Tuples have just two methods, `count` and `index`. A tuple is
            **hashable only if all its items are**, so a tuple of strings and numbers can be a
            dict key or a set member, but a tuple holding a list cannot.
            """
        ),
        code(
            """
            match_ratings = (5, 4, 5, 3, 5)
            print(f"{match_ratings.count(5)=}, {match_ratings.index(3)=}")
            print(f"{hash((1, 'a', (2, 3))) == hash((1, 'a', (2, 3)))=}")
            try:
                hash((1, [2, 3]))
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            sales_by_country_and_product = {("IN", "dosa"): 1200, ("US", "dosa"): 150}
            print(f"{sales_by_country_and_product[('IN', 'dosa')]=}")
            print(f"{isinstance((1, 'a'), Hashable)=}, {isinstance((1, []), Hashable)=}")
            print("  ^ the Hashable ABC checks the type only; hash() checks the items")
            """
        ),
        md(
            """
            #### Under the hood: tuples are smaller and built once

            A tuple stores its item pointers inline, with no spare capacity and no separate array,
            so it is smaller than the equivalent list. A tuple of constants is built once at
            compile time: `dis` shows a single `LOAD_CONST`, while the list is rebuilt on every
            run. (Bytecode names vary by Python version.)
            """
        ),
        code(
            """
            show_size("tuple (1, 2, 3)", (1, 2, 3))
            show_size("list  [1, 2, 3]", [1, 2, 3])
            appended_list = []
            for number in (1, 2, 3):
                appended_list.append(number)
            show_size("list built by append", appended_list)
            dis.dis(compile("rgb_tuple = (255, 153, 51)", "<tuple>", "exec"))
            dis.dis(compile("rgb_list = [255, 153, 51]", "<list>", "exec"))
            """
        ),
        md("#### Predict the output: the `t[0] += [1]` puzzle"),
        *predict_cells(
            snippet="""
            pair_of_lists = ([1, 2], "x")
            try:
                pair_of_lists[0] += [3]
            except TypeError as error:
                print(type(error).__name__)
            print(pair_of_lists)
            """,
            answer="""
            `TypeError`, then `([1, 2, 3], 'x')`. The statement **both** raises and mutates.
            `pair_of_lists[0] += [3]` first runs `list.__iadd__`, which extends the inner list in
            place and succeeds; then it tries to store the result back into slot 0 of the tuple,
            which fails because tuples do not support item assignment.
            """,
            proof="""
            pair_of_lists = ([1, 2], "x")
            try:
                pair_of_lists[0] += [3]
            except TypeError as error:
                print(type(error).__name__)
            print(pair_of_lists)
            """,
        ),
        md(
            """
            The bytecode shows the two steps: an in-place add (`BINARY_OP` with `+=`) followed by
            `STORE_SUBSCR`, and the error comes from the store.
            """
        ),
        code(
            """
            dis.dis(compile("pair_of_lists[0] += [3]", "<puzzle>", "exec"))
            """
        ),
    ]


def _named_tuple_range_array_cells() -> list[NotebookNode]:
    """1.5.6 Named tuples, 1.5.7 Ranges, 1.5.8 Arrays."""
    return [
        md(
            """
            ### 1.5.6 Named tuples

            A **named tuple** is a tuple subclass whose items also have names. It is still
            immutable, still unpacks, and costs no more memory than a plain tuple.
            `collections.namedtuple` builds one from a field list:

            | API | What it does |
            | --- | --- |
            | `_fields` | tuple of field names |
            | `_make(iterable)` | build an instance from any iterable (a CSV row, a DB row) |
            | `_asdict()` | a `dict` of field name → value |
            | `_replace(**changes)` | a modified **copy** (the original is unchanged) |

            The leading underscore avoids clashes with field names; these methods are public.
            """
        ),
        code(
            """
            GeoPoint = namedtuple("GeoPoint", ["latitude", "longitude"])
            office_point = GeoPoint(12.97, 77.59)
            print(f"{office_point=}, {office_point.latitude=}, {office_point[1]=}")
            point_latitude, point_longitude = office_point
            print(f"{GeoPoint._fields=}")
            print(f"{GeoPoint._make(['28.61', '77.21'])=}  (values are not converted)")
            print(f"{office_point._asdict()=}")
            moved_point = office_point._replace(longitude=77.60)
            print(f"{moved_point=}, {office_point=}  (original unchanged)")
            try:
                office_point.latitude = 0.0
            except AttributeError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **`typing.NamedTuple`** is the class syntax for the same thing: type-annotated fields,
            **defaults** (fields with defaults must come last), a docstring and **methods**.
            Prefer it in new code. `LogEntry` comes back in 1.5.11 and in the Phase 1 project.
            """
        ),
        code(
            '''
            class LogEntry(NamedTuple):
                """One parsed line of an access log."""

                level: str
                message: str
                status_code: int = 200

                def is_error(self) -> bool:
                    """Return True for ERROR entries and 5xx status codes."""
                    return self.level == "ERROR" or self.status_code >= 500


            placed_entry = LogEntry("INFO", "order placed")
            failed_entry = LogEntry("WARNING", "gateway timeout", 504)
            print(f"{placed_entry=}, {placed_entry.is_error()=}")
            print(f"{failed_entry.is_error()=}, {LogEntry._field_defaults=}")
            print(f"{isinstance(placed_entry, tuple)=}, {placed_entry == ('INFO', 'order placed', 200)=}")
            '''
        ),
        md(
            """
            ### 1.5.7 Ranges (`range`)

            A `range` is a **lazy, immutable sequence** of integers. It stores only `start`,
            `stop` and `step`, so its size never depends on its length, and `len`, indexing,
            slicing and `in` (for ints) are computed arithmetically in **O(1)**. Negative steps
            count down; `stop` is always excluded.
            """
        ),
        code(
            """
            page_offsets = range(0, 95, 20)
            print(f"{page_offsets=}, {list(page_offsets)=}")
            print(f"{list(range(10, 0, -3))=}, {list(range(5, 0, -1))=}")
            huge_range = range(0, 10**18, 7)
            print(f"{len(huge_range)=:,}")
            print(f"{7 * 10**15 in huge_range=}, {7 * 10**15 + 1 in huge_range=}")
            print(f"{huge_range[10**12]=:,}, {huge_range[-1]=:,}")
            print(f"{huge_range[::2]=}  (slicing returns another range)")
            print(f"{sys.getsizeof(huge_range)=} bytes, {sys.getsizeof(range(3))=} bytes")
            try:
                page_offsets[0] = 5
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            ### 1.5.8 Arrays (`array.array`)

            A list of floats stores a pointer per item **plus** a separate 24-byte `float` object
            per item. `array.array` stores raw machine values of one type (type code `"d"` =
            C double, 8 bytes) in one block. Use it for long numeric series when memory matters
            (NumPy, covered later, does the same and adds fast math).
            """
        ),
        code(
            """
            reading_count = 100_000
            readings_list = [reading_index * 0.5 for reading_index in range(reading_count)]
            readings_array = array.array("d", readings_list)
            list_total_bytes = sys.getsizeof(readings_list) + sum(
                sys.getsizeof(reading) for reading in readings_list
            )
            array_total_bytes = sys.getsizeof(readings_array)
            print(f"list of floats: {list_total_bytes:>10,} bytes (list + float objects)")
            print(f"array('d'):     {array_total_bytes:>10,} bytes")
            print(f"ratio: {list_total_bytes / array_total_bytes:.1f}x")
            print(f"{readings_array.typecode=}, {readings_array.itemsize=}, {readings_array[:3]=}")
            print(f"append a str: {raised_error_name(lambda: readings_array.append('x'))}")
            """
        ),
    ]


def _list_reference_cells() -> list[NotebookNode]:
    """1.5.9 Method reference — list: one demo cell per table row."""
    return [
        md(
            """
            ### 1.5.9 Method reference — `list`

            Every row gets a demo cell below.

            | Method / operation | What it does | Returns | Cost |
            | --- | --- | --- | --- |
            | `append(x)` | add one item at the end | `None` | O(1) amortized |
            | `extend(iterable)` / `+= iterable` | add every item of an iterable | `None` / same list | O(k) |
            | `insert(i, x)` | insert before index `i` | `None` | O(n) |
            | `remove(x)` | delete the first item equal to `x` (`ValueError` if absent) | `None` | O(n) |
            | `pop()` / `pop(i)` | remove and return the last / i-th item (`IndexError` if empty) | item | O(1) / O(n) |
            | `clear()` | remove every item | `None` | O(n) |
            | `index(x[, start[, end]])` | position of the first `x` (`ValueError` if absent) | `int` | O(n) |
            | `count(x)` | number of items equal to `x` | `int` | O(n) |
            | `sort(*, key=None, reverse=False)` | stable in-place sort | `None` | O(n log n) |
            | `reverse()` | reverse in place | `None` | O(n) |
            | `copy()` | shallow copy (same as `[:]`, `list(x)`) | new `list` | O(n) |
            | `items[i]`, `items[i] = x` | read / replace by index (negative indexes allowed) | item / — | O(1) |
            | `items[a:b:c]`, `items[a:b] = iterable` | slice copy / slice replacement | new `list` / — | O(k) |
            | `del items[i]`, `del items[a:b]` | delete by index or slice | — | O(n) |
            | `x in items` | membership by `==` | `bool` | O(n) |
            | `items + other`, `items * n` | concatenate / repeat into a new list | new `list` | O(n + m) |
            | `len`, `min`, `max`, `sum`, `sorted`, `reversed`, `enumerate`, `any`, `all` | built-ins that work on lists | varies | O(n) |
            | `==`, `<` | element-wise, lexicographic comparison | `bool` | O(n) |
            """
        ),
        md(
            """
            #### `list`

            **`append(x)`**: one item at the end; the call returns `None`.
            """
        ),
        code(
            """
            shopping_list = ["rice"]
            append_result = shopping_list.append("dal")
            print(f"{shopping_list=}, {append_result=}")
            """
        ),
        md("**`extend(iterable)` / `+= iterable`**: every item of any iterable, in place."),
        code(
            """
            shopping_list = ["rice"]
            shopping_list.extend(("dal", "ghee"))
            list_before_augmented_add = shopping_list
            shopping_list += "ab"
            print(f"{shopping_list=}  (a str is an iterable of characters)")
            print(f"{shopping_list is list_before_augmented_add=}")
            """
        ),
        md("**`insert(i, x)`**: before index `i`; an index past the end appends."),
        code(
            """
            shopping_list = ["rice", "ghee"]
            shopping_list.insert(1, "dal")
            shopping_list.insert(0, "salt")
            shopping_list.insert(100, "sugar")
            shopping_list.insert(-1, "tea")
            print(f"{shopping_list=}")
            """
        ),
        md("**`remove(x)`**: the first equal item; `ValueError` if absent."),
        code(
            """
            shopping_list = ["rice", "dal", "rice"]
            shopping_list.remove("rice")
            print(f"{shopping_list=}")
            print(f"remove missing: {raised_error_name(lambda: shopping_list.remove('oil'))}")
            """
        ),
        md("**`pop()` / `pop(i)`**: remove and return the last or the i-th item."),
        code(
            """
            shopping_list = ["rice", "dal", "ghee", "salt"]
            print(f"{shopping_list.pop()=}, {shopping_list.pop(0)=}, {shopping_list=}")
            print(f"pop from empty: {raised_error_name(lambda: [].pop())}")
            print(f"pop bad index: {raised_error_name(lambda: ['rice'].pop(5))}")
            """
        ),
        md("**`clear()`**: empties the list in place, so every alias sees the change."),
        code(
            """
            shopping_list = ["rice", "dal"]
            same_list_alias = shopping_list
            shopping_list.clear()
            print(f"{shopping_list=}, {same_list_alias=}")
            """
        ),
        md("**`index(x[, start[, end]])`**: position of the first match in the window."),
        code(
            """
            shopping_list = ["rice", "dal", "ghee", "dal"]
            print(f"{shopping_list.index('dal')=}, {shopping_list.index('dal', 2)=}")
            print(f"not in window: {raised_error_name(lambda: shopping_list.index('rice', 1, 3))}")
            """
        ),
        md("**`count(x)`**: how many items are `==` to `x`."),
        code(
            """
            shopping_list = ["rice", "dal", "rice", "Rice"]
            print(f"{shopping_list.count('rice')=}, {shopping_list.count('oil')=}")
            """
        ),
        md("**`sort(*, key=None, reverse=False)`**: stable, in place, keyword-only arguments."),
        code(
            """
            shopping_list = ["ghee", "Rice", "dal", "salt"]
            shopping_list.sort()
            print(f"{shopping_list=}  (uppercase first)")
            shopping_list.sort(key=str.lower, reverse=True)
            print(f"{shopping_list=}")
            print(f"positional key: {raised_error_name(lambda: shopping_list.sort(str.lower))}")
            """
        ),
        md("**`reverse()`**: in place, returns `None`."),
        code(
            """
            shopping_list = ["rice", "dal", "ghee"]
            print(f"{shopping_list.reverse()=}, {shopping_list=}")
            """
        ),
        md("**`copy()`**: a new list holding the same item objects."),
        code(
            """
            shopping_list = ["rice", ["dal", "ghee"]]
            copied_list = shopping_list.copy()
            print(f"{copied_list == shopping_list=}, {copied_list is shopping_list=}")
            print(f"{copied_list[1] is shopping_list[1]=}  (shallow)")
            """
        ),
        md(
            "**`items[i]`, `items[i] = x`**: read or replace one slot; negative indexes count from the end."
        ),
        code(
            """
            shopping_list = ["rice", "dal", "ghee"]
            print(f"{shopping_list[0]=}, {shopping_list[-1]=}")
            shopping_list[-1] = "butter"
            print(f"{shopping_list=}")
            print(f"assign past the end: {raised_error_name(lambda: shopping_list.__setitem__(5, 'x'))}")
            """
        ),
        md("**`items[a:b:c]`, `items[a:b] = iterable`**: copy a slice, or replace one."),
        code(
            """
            shopping_list = ["rice", "dal", "ghee", "salt", "tea"]
            print(f"{shopping_list[1:4]=}, {shopping_list[::2]=}, {shopping_list[::-1]=}")
            shopping_list[1:3] = ("moong dal", "toor dal", "urad dal")
            print(f"{shopping_list=}")
            """
        ),
        md(
            "**`del items[i]`, `del items[a:b]`**: delete by position or slice (an extended slice works too)."
        ),
        code(
            """
            shopping_list = ["rice", "dal", "ghee", "salt", "tea", "jam"]
            del shopping_list[0]
            del shopping_list[-2:]
            print(f"{shopping_list=}")
            del shopping_list[::2]
            print(f"{shopping_list=}")
            """
        ),
        md(
            """
            **`x in items`**: a linear scan with `==`. CPython checks identity first, so an object
            is always found in a list that holds it, even `nan`, which is not equal to itself.
            """
        ),
        code(
            """
            shopping_list = ["rice", "dal"]
            print(f"{'dal' in shopping_list=}, {'oil' not in shopping_list=}")
            not_a_number = float("nan")
            print(f"{not_a_number == not_a_number=}, {not_a_number in [not_a_number]=}")
            print(f"{float('nan') in [float('nan')]=}  (two different nan objects)")
            """
        ),
        md(
            """
            **`items + other`, `items * n`**: new lists. Repetition copies **references**, which
            matters when the item is mutable (see Lab 1.5, exercise 4).
            """
        ),
        code(
            """
            breakfast_list = ["idli", "dosa"]
            print(f"{breakfast_list + ['vada']=}, {breakfast_list * 2=}, {breakfast_list=}")
            repeated_rows = [[]] * 3
            repeated_rows[0].append("x")
            print(f"{repeated_rows=}  (three references to one inner list)")
            """
        ),
        md(
            "**Built-ins that work on lists**: `len`, `min`, `max`, `sum`, `sorted`, `reversed`, `enumerate`, `any`, `all`."
        ),
        code(
            """
            daily_sales = [1200, 950, 0, 1800, 1430]
            print(f"{len(daily_sales)=}, {min(daily_sales)=}, {max(daily_sales)=}, {sum(daily_sales)=}")
            print(f"{sorted(daily_sales)=}, {list(reversed(daily_sales))=}")
            for day_number, sales_amount in enumerate(daily_sales, start=1):
                print(f"day {day_number}: ₹{sales_amount:,}")
            print(f"{any(sale == 0 for sale in daily_sales)=}, {all(daily_sales)=}")
            print(f"{max([], default=0)=}  (default avoids ValueError on empty input)")
            """
        ),
        md(
            """
            **`==`, `<`**: compare item by item; the first difference decides, and a shorter list
            that is a prefix of a longer one is smaller.
            """
        ),
        code(
            """
            print(f"{[1, 2, 3] == [1, 2, 3]=}, {[1, 2] == [1.0, 2.0]=}")
            print(f"{[1, 2, 3] < [1, 3]=}  (decided at index 1)")
            print(f"{[1, 2] < [1, 2, 0]=}  (prefix is smaller)")
            print(f"{['b'] > ['a', 'z']=}")
            print(f"mixed types: {raised_error_name(lambda: [1, 'a'] < [1, 2])}")
            """
        ),
    ]


def _tuple_range_reference_cells() -> list[NotebookNode]:
    """1.5.10 Method reference — tuple, namedtuple and range."""
    return [
        md(
            """
            ### 1.5.10 Method reference — `tuple`, `namedtuple` and `range`

            | Type | Method / operation | What it does |
            | --- | --- | --- |
            | `tuple` | `count(x)`, `index(x[, start[, end]])` | the only two methods — tuples are immutable |
            | `tuple` | indexing, slicing, `in`, `+`, `*`, `len`, comparison | same semantics as lists, but always returns new tuples |
            | `tuple` | `hash(t)` | works when every item is hashable — enables dict keys and set members |
            | `tuple` | unpacking `a, b = t`, `first, *rest = t` | the most common way to read tuples |
            | `namedtuple` | `_make(iterable)`, `_asdict()`, `_replace(**changes)`, `_fields`, `_field_defaults` | construction, conversion, "modified copy", introspection |
            | `range` | `start`, `stop`, `step`, `count(x)`, `index(x)` | attributes and O(1) arithmetic lookups |
            """
        ),
        md(
            """
            #### `tuple`

            **`count(x)`, `index(x[, start[, end]])`**: the only two methods.
            """
        ),
        code(
            """
            weekday_codes = ("Mon", "Tue", "Wed", "Tue", "Fri")
            tuple_method_names = [name for name in dir(tuple) if not name.startswith("_")]
            print(f"{tuple_method_names=}")
            print(f"{weekday_codes.count('Tue')=}, {weekday_codes.index('Tue', 2)=}")
            print(f"missing: {raised_error_name(lambda: weekday_codes.index('Sun'))}")
            """
        ),
        md(
            "**Indexing, slicing, `in`, `+`, `*`, `len`, comparison**: like lists, but every result is a new tuple."
        ),
        code(
            """
            rgb_colour = (255, 153, 51)
            print(f"{rgb_colour[0]=}, {rgb_colour[-2:]=}, {153 in rgb_colour=}, {len(rgb_colour)=}")
            print(f"{rgb_colour + (128,)=}, {(0,) * 3=}")
            print(f"{(1, 2, 3) < (1, 3)=}, {(1, 2) == (1, 2)=}, {(1, 2) == [1, 2]=}")
            """
        ),
        md("**`hash(t)`**: works only when every item is hashable."),
        code(
            """
            route_distances = {("Delhi", "Agra"): 233, ("Mumbai", "Pune"): 148}
            print(f"{route_distances[('Delhi', 'Agra')]=}")
            visited_cells = {(0, 0), (0, 1), (0, 0)}
            print(f"{visited_cells=}")
            print(f"tuple holding a list: {raised_error_name(lambda: hash(('Delhi', ['Agra'])))}")
            """
        ),
        md(
            "**Unpacking `a, b = t`, `first, *rest = t`**: the most common way to read a tuple; the counts must match."
        ),
        code(
            """
            delivery_record = ("A-17", "Asha", "Pune", 450)
            order_id, customer_name, delivery_city, amount_due = delivery_record
            first_field, *remaining_fields = delivery_record
            print(f"{order_id=}, {amount_due=}, {first_field=}, {remaining_fields=}")
            try:
                order_id, customer_name = delivery_record
            except ValueError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md(
            """
            #### `namedtuple`

            **`_make`, `_asdict`, `_replace`, `_fields`, `_field_defaults`**: construction,
            conversion, modified copy and introspection. `defaults=` applies to the *rightmost*
            fields.
            """
        ),
        code(
            """
            OrderLine = namedtuple("OrderLine", ["item", "quantity", "unit_price"], defaults=[1, 0])
            csv_line = OrderLine._make(["dosa", 2, 60])
            print(f"{csv_line=}")
            print(f"{csv_line._asdict()=}")
            print(f"{csv_line._replace(quantity=3)=}")
            print(f"{OrderLine._fields=}, {OrderLine._field_defaults=}")
            print(f"{OrderLine('tea')=}  (defaults filled in)")
            """
        ),
        md(
            """
            #### `range`

            **`start`, `stop`, `step`, `count(x)`, `index(x)`**: the three attributes, plus
            lookups computed arithmetically.
            """
        ),
        code(
            """
            even_hours = range(0, 24, 2)
            print(f"{even_hours.start=}, {even_hours.stop=}, {even_hours.step=}")
            print(f"{even_hours.count(14)=}, {even_hours.count(15)=}, {even_hours.index(14)=}")
            print(f"{range(10**18).index(10**17)=:,}  (instant: no scan)")
            print(f"not in range: {raised_error_name(lambda: even_hours.index(15))}")
            """
        ),
    ]


def _use_case_cells() -> list[NotebookNode]:
    """1.5.11 Real-world use cases."""
    return [
        md(
            """
            ### 1.5.11 Real-world use cases

            **`list`**: an ordered, changing collection: shopping-cart items, a page of API
            results, rows read from a CSV file, or a stack (`append` + `pop`). Ordered processing
            queues of moderate size also fit, as long as you take items from the end.
            """
        ),
        code(
            """
            undo_stack: list[str] = []
            for editor_action in ["type 'a'", "type 'b'", "bold"]:
                undo_stack.append(editor_action)
            print(f"undo {undo_stack.pop()!r}; remaining stack: {undo_stack}")
            api_page = [{"id": 1, "item": "idli"}, {"id": 2, "item": "dosa"}]
            print(f"{[result['item'] for result in api_page]=}")
            csv_text = "id,item,price\\n1,idli,40\\n2,dosa,60\\n"
            header_row, *data_rows = csv.reader(io.StringIO(csv_text))
            print(f"{header_row=}, {data_rows=}")
            """
        ),
        md(
            """
            **`tuple`**: a fixed record whose positions mean something: database rows (the
            `sqlite3` module returns tuples), `(latitude, longitude)`, several return values from
            one function, composite dict keys like `(country, product)`, and constants that must
            not change.
            """
        ),
        code(
            '''
            WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


            def lowest_and_highest(prices: list[int]) -> tuple[int, int]:
                """Return the lowest and highest price as one tuple."""
                return min(prices), max(prices)


            cheapest_price, dearest_price = lowest_and_highest([40, 60, 35, 120])
            print(f"{cheapest_price=}, {dearest_price=}, {WEEKDAY_NAMES[4]=}")
            connection = sqlite3.connect(":memory:")
            connection.execute("CREATE TABLE stores (city TEXT, latitude REAL, longitude REAL)")
            connection.execute("INSERT INTO stores VALUES ('Pune', 18.52, 73.86)")
            store_row = connection.execute("SELECT * FROM stores").fetchone()
            connection.close()
            print(f"{store_row=}, {type(store_row).__name__=}")
            units_sold = {("IN", "dosa"): 1200, ("IN", "idli"): 800, ("US", "dosa"): 150}
            print(f"{sum(count for (country, _), count in units_sold.items() if country == 'IN')=}")
            '''
        ),
        md(
            """
            **`namedtuple` / `NamedTuple`**: a lightweight read-only record with field names,
            such as a parsed log line or a CSV row. This reuses `LogEntry` from 1.5.6.
            """
        ),
        code(
            """
            raw_log_lines = [
                "INFO|order placed|201",
                "ERROR|payment failed|502",
                "WARNING|slow response|200",
            ]
            parsed_entries = []
            for raw_log_line in raw_log_lines:
                level, message, status_text = raw_log_line.split("|")
                parsed_entries.append(LogEntry(level, message, int(status_text)))
            print([entry.message for entry in parsed_entries if entry.is_error()])
            print(f"{parsed_entries[0]._asdict()=}")
            """
        ),
        md(
            """
            **`range`**: index loops, pagination offsets (`range(0, total, page_size)`) and
            membership checks on numeric intervals.
            """
        ),
        code(
            """
            total_results, page_size = 95, 20
            for page_number, page_offset in enumerate(range(0, total_results, page_size), start=1):
                page_end = min(page_offset + page_size, total_results)
                print(f"page {page_number}: results {page_offset + 1}-{page_end}")
            working_age = range(18, 61)
            print(f"{25 in working_age=}, {61 in working_age=}, {17.5 in working_age=}")
            """
        ),
        md(
            """
            **`array.array`**: large numeric series where memory matters, such as sensor readings.
            The type code `"f"` stores 4-byte C floats, and `tobytes()` gives the raw block,
            ready for a file or a socket.
            """
        ),
        code(
            """
            temperature_readings = array.array("f")
            for minute in range(60 * 24):
                temperature_readings.append(20 + (minute % 120) / 10)
            average_temperature = sum(temperature_readings) / len(temperature_readings)
            print(f"{len(temperature_readings)=}, {average_temperature=:.2f}")
            print(f"{len(temperature_readings.tobytes())=:,} bytes for a day of readings")
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.5."""
    return [
        md(
            """
            ### Lab 1.5

            Three coding exercises and a set of predict-the-output questions on aliasing. For each
            coding exercise, replace the `raise NotImplementedError` in the stub, then run the
            check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — sort employee records by several keys

            Order employees by **department ascending**, then **salary descending**, then
            **name ascending**. Write it twice:

            1. `sort_employees_multipass(employees)`: several stable `sorted()` passes, with no
               tuple keys.
            2. `sort_employees_tuple_key(employees)`: one `sorted()` call with a tuple key.

            Both return a **new** list and leave the input unchanged. Run the next cell first; it
            defines `Employee` and the sample data.
            """
        ),
        code(
            '''
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
            '''
        ),
        md(
            """
            The two stubs:
            """
        ),
        code(
            '''
            def sort_employees_multipass(employees: list[Employee]) -> list[Employee]:
                """Sort by department, salary (high first), name using stable multi-pass sorting."""
                raise NotImplementedError("Lab 1.5: implement sort_employees_multipass()")


            def sort_employees_tuple_key(employees: list[Employee]) -> list[Employee]:
                """Sort by department, salary (high first), name using one tuple key."""
                raise NotImplementedError("Lab 1.5: implement sort_employees_tuple_key()")
            '''
        ),
        md(
            """
            The check cell defines two helpers: `employee_names` (the names in order) and
            `returns_new_list` (checks the input list is left alone).
            """
        ),
        code(
            '''
            def employee_names(employees: list[Employee]) -> list[str]:
                """Return just the names, in order."""
                return [employee.name for employee in employees]


            def returns_new_list(sort_function: Callable[[list[Employee]], list[Employee]]) -> bool:
                """Return True if sort_function returns a new list and leaves its argument alone."""
                employees_argument = list(SAMPLE_EMPLOYEES)
                sorted_employees = sort_function(employees_argument)
                return sorted_employees is not employees_argument and employees_argument == SAMPLE_EMPLOYEES


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
                    ("multi-pass returns a new list", lambda: returns_new_list(sort_employees_multipass), True),
                    ("tuple-key returns a new list", lambda: returns_new_list(sort_employees_tuple_key), True),
                    ("empty list", lambda: sort_employees_tuple_key([]), []),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — `transpose(matrix)`

            Write `transpose(matrix: list[list[T]]) -> list[list[T]]` using `zip(*matrix)`:
            rows become columns. Return a list of **lists** (not tuples). `[]` transposes to
            `[]`. If the rows have different lengths, raise `ValueError` (*hint:*
            `zip(..., strict=True)`).
            """
        ),
        code(
            '''
            def transpose[T](matrix: list[list[T]]) -> list[list[T]]:
                """Return the transpose of a rectangular matrix given as a list of rows."""
                raise NotImplementedError("Lab 1.5: implement transpose()")
            '''
        ),
        md(
            """
            Run the checks.
            """
        ),
        code(
            """
            run_checks(
                [
                    ("2x3 becomes 3x2", lambda: transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]]),
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
            """
        ),
        md(
            """
            #### Exercise 3 — `dedupe_preserving_order(items)`

            Write `dedupe_preserving_order(items: Iterable[T]) -> list[T]` for hashable items:
            keep the **first** occurrence of each item, in the original order. It must accept any
            iterable, including a one-shot iterator. Note that `1`, `1.0` and `True` are equal
            and hash the same, so they count as duplicates.
            """
        ),
        code(
            '''
            def dedupe_preserving_order[T](items: Iterable[T]) -> list[T]:
                """Return the items without duplicates, keeping first occurrences in order."""
                raise NotImplementedError("Lab 1.5: implement dedupe_preserving_order()")
            '''
        ),
        md(
            """
            Run the checks.
            """
        ),
        code(
            """
            run_checks(
                [
                    ("ints", lambda: dedupe_preserving_order([3, 1, 3, 2, 1]), [3, 1, 2]),
                    ("strings", lambda: dedupe_preserving_order(["b", "a", "b", "c", "a"]), ["b", "a", "c"]),
                    ("empty", lambda: dedupe_preserving_order([]), []),
                    (
                        "one-shot iterator",
                        lambda: dedupe_preserving_order(iter("mississippi")),
                        ["m", "i", "s", "p"],
                    ),
                    ("1, 1.0 and True are equal", lambda: dedupe_preserving_order([1, 1.0, True, 2]), [1, 2]),
                    ("tuples", lambda: dedupe_preserving_order([(1, 2), (1, 2), (2, 1)]), [(1, 2), (2, 1)]),
                ]
            )
            """
        ),
        md("#### Exercise 4 — predict the output (aliasing)"),
        *predict_cells(
            snippet="""
            seating_grid = [[0] * 3] * 3
            seating_grid[0][0] = 1
            print(seating_grid)
            """,
            answer="""
            `[[1, 0, 0], [1, 0, 0], [1, 0, 0]]`. `[0] * 3` builds one inner list, and `* 3` on the
            outer list copies the **reference** to it three times. All three rows are the same
            object, so changing one changes them all. (`[0] * 3` itself is fine: ints are
            immutable, so sharing them is harmless.)
            """,
            proof="""
            seating_grid = [[0] * 3] * 3
            seating_grid[0][0] = 1
            print(seating_grid)
            print(f"{seating_grid[0] is seating_grid[1]=}")
            """,
        ),
        *predict_cells(
            snippet="""
            seating_grid = [[0] * 3 for _ in range(3)]
            seating_grid[0][0] = 1
            print(seating_grid)
            """,
            answer="""
            `[[1, 0, 0], [0, 0, 0], [0, 0, 0]]`. The comprehension evaluates `[0] * 3` once per
            row, so each row is a separate list. This is the correct way to build a grid.
            """,
            proof="""
            seating_grid = [[0] * 3 for _ in range(3)]
            seating_grid[0][0] = 1
            print(seating_grid)
            print(f"{seating_grid[0] is seating_grid[1]=}")
            """,
        ),
        *predict_cells(
            snippet="""
            pending_orders = processed_orders = []
            pending_orders.append("A-17")
            print(processed_orders, pending_orders is processed_orders)
            """,
            answer="""
            `['A-17'] True`. Chained assignment binds both names to **one** list object. Write
            `pending_orders, processed_orders = [], []` for two lists.
            """,
            proof="""
            pending_orders = processed_orders = []
            pending_orders.append("A-17")
            print(processed_orders, pending_orders is processed_orders)
            """,
        ),
        *predict_cells(
            snippet="""
            shelf_rows = [[]] * 2
            shelf_rows[0] += ["jam"]
            shelf_rows[1] = shelf_rows[1] + ["tea"]
            print(shelf_rows)
            """,
            answer="""
            `[['jam'], ['jam', 'tea']]`. Both slots start as the same empty list. `+=` extends
            that shared list in place, so both rows show `'jam'`. `shelf_rows[1] + ["tea"]` builds
            a **new** list and rebinds only slot 1.
            """,
            proof="""
            shelf_rows = [[]] * 2
            shelf_rows[0] += ["jam"]
            shelf_rows[1] = shelf_rows[1] + ["tea"]
            print(shelf_rows)
            """,
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.5."""
    return [
        md(
            """
            ### Recap — Unit 1.5

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Sequence operations | Indexing, slicing, `in`, `len`, `min`, `max`, `count`, `index` on every sequence; `range` has no `+`/`*` | Array methods |
            | `list` internals | Dynamic array of pointers with spare capacity; `append` is O(1) amortized | `Array` |
            | Front operations | `pop(0)` and `insert(0, x)` are O(n) | `shift`, `unshift` |
            | Mutating methods | Return `None`; `sorted()` and `+` return new lists | `push` returns the length |
            | `+=` vs `+` | `+=` extends in place (any iterable); `+` builds a new list | `push(...items)` vs `concat` |
            | Slice assignment | Replaces a slice, may change the length; extended slices must match | `splice` |
            | Copies | `copy()`, `[:]`, `list()` are shallow | `[...arr]`, `slice()` |
            | Sorting | Stable Timsort; `key=`, `reverse=`, `itemgetter`, tuple keys with negation | `sort((a, b) => …)` |
            | `tuple` | The comma makes it; immutable; hashable if all items are | `Object.freeze([])` |
            | `t[0] += [x]` | Mutates the inner list *and* raises `TypeError` | — |
            | Named tuples | `namedtuple` / `NamedTuple`: fields, defaults, `_replace`, `_asdict` | object literal |
            | `range` | Lazy, O(1) `len`/`in`/index, constant memory | — |
            | `array.array` | Typed, compact numeric storage | `Float64Array` |
            | `[[0] * 3] * 3` | Repeats references; build grids with a comprehension | `Array(3).fill([])` has the same bug |

            **Further reading**

            - [Sequence types — `list`, `tuple`, `range`](https://docs.python.org/3/library/stdtypes.html#sequence-types-list-tuple-range),
              [more on lists](https://docs.python.org/3/tutorial/datastructures.html#more-on-lists)
            - [Sorting techniques](https://docs.python.org/3/howto/sorting.html),
              [`operator.itemgetter` / `attrgetter`](https://docs.python.org/3/library/operator.html#operator.itemgetter)
            - [`collections.namedtuple`](https://docs.python.org/3/library/collections.html#collections.namedtuple),
              [`typing.NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple)
            - [`array`](https://docs.python.org/3/library/array.html),
              [Time complexity of CPython operations](https://wiki.python.org/moin/TimeComplexity)
            - [PEP 3132 — Extended iterable unpacking](https://peps.python.org/pep-3132/),
              [PEP 448 — Additional unpacking generalizations](https://peps.python.org/pep-0448/),
              [PEP 695 — Type parameter syntax](https://peps.python.org/pep-0695/) (used by the
              `transpose[T]` stub)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.5 and Lab 1.5."""
    return [
        *_overview_cells(),
        *_list_internals_cells(),
        *_list_methods_cells(),
        *_sorting_cells(),
        *_tuple_cells(),
        *_named_tuple_range_array_cells(),
        *_list_reference_cells(),
        *_tuple_range_reference_cells(),
        *_use_case_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
