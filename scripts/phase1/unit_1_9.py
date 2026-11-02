"""Unit 1.9 — Iteration, Comprehensions and Built-in Functions (with Lab 1.9)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import ast
import datetime as dt
import dis
import io
import operator
import subprocess
import sys
import timeit
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import IO, Any, NamedTuple


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


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (default: the working directory) to the folder holding pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "pyproject.toml").exists():
            return folder
    raise FileNotFoundError("pyproject.toml not found above the working directory")


scratch_dir = find_repo_root() / "notebooks" / "_scratch"
scratch_dir.mkdir(parents=True, exist_ok=True)
print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.9 — Iteration, Comprehensions and Built-in Functions

            **Objectives**

            - Explain the iteration protocol (`iter`, `next`, `StopIteration`) and desugar a
              `for` loop by hand.
            - Use `enumerate`, `zip`, `reversed`, `sorted` and `range` instead of index
              arithmetic.
            - Write list, dict and set comprehensions, and know when a plain loop reads better.
            - Know every commonly used built-in function, grouped by purpose, and which ones are
              dangerous.
            - Choose between `map` / `filter` and comprehensions, and write idiomatic loops.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `for (const x of items)` | `for item in items` | Same idea: both use an iteration protocol |
            | `obj[Symbol.iterator]()` | `iter(obj)` → calls `obj.__iter__()` | |
            | `it.next()` → `{value, done}` | `next(it)` → value, or raises `StopIteration` | The end is an exception, not a flag |
            | `items.map(f)`, `items.filter(f)` | `map(f, items)`, `filter(f, items)` | Python's are **lazy, single-use iterators**, not arrays |
            | `items.map(...).filter(...)` | `[f(x) for x in items if cond(x)]` | Comprehensions are the idiomatic form |
            | `items.entries()` | `enumerate(items)` | Gives `(index, item)` pairs; `start=` sets the first index |
            | lodash `zip` | `zip(a, b, strict=True)` | Built in; truncates silently without `strict=True` |
            | `items.some(f)`, `items.every(f)` | `any(...)`, `all(...)` | Take any iterable of truthy values |
            | `Math.max(...items)` | `max(items, key=..., default=...)` | Works on any comparable values; `default` for empty input |
            | `typeof x`, `x instanceof C` | `type(x)`, `isinstance(x, C)` | |
            | `eval(code)` | `eval(code)` | Just as dangerous; parse data with `ast.literal_eval` or `json.loads` |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _protocol_cells() -> list[NotebookNode]:
    """1.9.1 The iteration protocol."""
    return [
        md(
            """
            ### 1.9.1 The iteration protocol

            Two roles:

            | Role | Has | Example |
            | --- | --- | --- |
            | **Iterable** | `__iter__()` returning a new iterator | `list`, `str`, `dict`, `range`, files |
            | **Iterator** | `__next__()` returning the next item or raising `StopIteration`, and `__iter__()` returning itself | `iter([1, 2])`, generators, `map`, `zip` |

            `iter(obj)` calls `obj.__iter__()`; `next(it)` calls `it.__next__()`. When the items
            run out, `__next__` raises `StopIteration`. The next cell walks a list by hand.
            """
        ),
        code(
            """
            queue_names = ["asha", "ravi"]
            name_iterator = iter(queue_names)
            print(f"{type(name_iterator).__name__=}")
            print(f"{next(name_iterator)=}")
            print(f"{next(name_iterator)=}")
            try:
                next(name_iterator)
            except StopIteration:
                print("StopIteration: the iterator is exhausted")
            print(f"{list(name_iterator)=}  (an exhausted iterator stays empty)")
            print(f"{iter(name_iterator) is name_iterator=}, {iter(queue_names) is queue_names=}")
            """
        ),
        md(
            """
            **The desugared `for` loop.** `for item in iterable: body` is exactly this:

            ```python
            hidden_iterator = iter(iterable)
            while True:
                try:
                    item = next(hidden_iterator)
                except StopIteration:
                    break
                body
            ```

            The next cell runs both versions side by side.
            """
        ),
        code(
            """
            order_totals = [120, 499, 999]

            for order_total in order_totals:
                print(f"for loop:     {order_total}")

            hidden_iterator = iter(order_totals)
            while True:
                try:
                    order_total = next(hidden_iterator)
                except StopIteration:
                    break
                print(f"desugared:    {order_total}")
            """
        ),
        md(
            """
            Any class can join the protocol. `Countdown` is an iterable: each `iter()` call
            returns a fresh `CountdownIterator`, so it can be looped over more than once.
            (Unit 1.13 writes the same thing in three lines with a generator.)
            """
        ),
        code(
            '''
            class CountdownIterator:
                """Iterator from start down to 1."""

                def __init__(self, start: int) -> None:
                    self.current = start

                def __iter__(self) -> CountdownIterator:
                    return self

                def __next__(self) -> int:
                    if self.current < 1:
                        raise StopIteration
                    self.current -= 1
                    return self.current + 1


            class Countdown:
                """Iterable: a new iterator per loop."""

                def __init__(self, start: int) -> None:
                    self.start = start

                def __iter__(self) -> CountdownIterator:
                    return CountdownIterator(self.start)


            launch = Countdown(3)
            print(f"{list(launch)=}, {list(launch)=}  (iterable: reusable)")
            single_pass = iter(launch)
            print(f"{list(single_pass)=}, {list(single_pass)=}  (iterator: one pass)")
            '''
        ),
        md(
            """
            #### Under the hood: `GET_ITER` and `FOR_ITER`

            In bytecode, a `for` loop is `GET_ITER` (call `iter()` once) followed by `FOR_ITER`
            (call `next()`; on `StopIteration`, jump past the loop body). The `StopIteration` is
            handled inside the interpreter, so no Python-level exception is raised for the normal
            end of a loop. Opcode names vary between versions.
            """
        ),
        code(
            '''
            def total_of(prices: list[int]) -> int:
                """Sum prices with an explicit loop."""
                running_total = 0
                for price in prices:
                    running_total += price
                return running_total


            print([instruction.opname for instruction in dis.get_instructions(total_of)])
            '''
        ),
        md(
            """
            **`iter(callable, sentinel)`**: the two-argument form calls `callable()` again and
            again and stops when the result **equals** `sentinel`. It turns "read until empty"
            loops into iterators. `stream.readline` returns `""` at the end of a text stream:
            """
        ),
        code(
            """
            access_log = io.StringIO("GET /\\nPOST /cart\\nGET /checkout\\n")
            for log_line in iter(access_log.readline, ""):
                print(f"line: {log_line.rstrip()}")
            """
        ),
        md(
            """
            With a `lambda` (1.10.7) the callable can pass arguments, which gives **fixed-size
            chunks**: read 4 bytes at a time until `read` returns `b""`. Lab 1.9, exercise 1,
            wraps this in a reusable function.
            """
        ),
        code(
            """
            upload_stream = io.BytesIO(b"PNG-image-bytes")
            chunk_list = list(iter(lambda: upload_stream.read(4), b""))
            print(f"{chunk_list=}")
            """
        ),
    ]


def _helper_cells() -> list[NotebookNode]:
    """1.9.2 Iteration helpers."""
    return [
        md(
            """
            ### 1.9.2 Iteration helpers

            Five built-ins remove almost every need for index arithmetic. Each returns a lazy
            iterator except `sorted` (a new list) and `range` (a lazy sequence object).

            **`enumerate(iterable, start=0)`** yields `(index, item)` pairs; `start=1` gives
            human numbering.
            """
        ),
        code(
            """
            checkout_steps = ["cart", "address", "payment"]
            for step_number, step_name in enumerate(checkout_steps, start=1):
                print(f"step {step_number}: {step_name}")
            print(f"{list(enumerate('ab'))=}")
            """
        ),
        md(
            """
            **`zip(*iterables, strict=False)`** pairs items up. By default it stops at the
            **shortest** input and silently drops the rest; `strict=True` (3.10) raises
            `ValueError` when the lengths differ, which is almost always what you want.
            """
        ),
        code(
            """
            product_names = ["tea", "rice", "ghee"]
            unit_prices = [249, 525]
            print(f"{list(zip(product_names, unit_prices, strict=False))=}  (ghee lost silently)")
            print(f"strict: {raised_error_name(lambda: list(zip(product_names, unit_prices, strict=True)))}")
            rows = [("tea", 249), ("rice", 525)]
            names_column, prices_column = zip(*rows, strict=True)  # zip(*rows) transposes
            print(f"{names_column=}, {prices_column=}")
            """
        ),
        md(
            """
            **`reversed(sequence)`** iterates backwards without copying. It needs a sequence
            (`len` + indexing) or a `__reversed__` method; dicts and their views support it since
            3.8. A generator does not.
            """
        ),
        code(
            """
            print(f"{list(reversed([1, 2, 3]))=}, {''.join(reversed('UPI'))=}")
            print(f"{list(reversed({'a': 1, 'b': 2}))=}, {list(reversed(range(3)))=}")
            print(f"generator: {raised_error_name(lambda: reversed(n for n in range(3)))}")
            """
        ),
        md(
            """
            **`sorted(iterable, *, key=None, reverse=False)`** accepts any iterable and returns a
            **new list**; the input is not changed (1.5.4 covers sorting in depth).
            """
        ),
        code(
            """
            stock_levels = {"tea": 5, "rice": 12, "ghee": 2}
            print(f"{sorted(stock_levels)=}  (keys)")
            print(f"{sorted(stock_levels, key=stock_levels.get, reverse=True)=}  (by stock)")
            print(f"{sorted('python')=}, {sorted({3, 1, 2})=}")
            """
        ),
        md(
            """
            **`range(start, stop, step)`** is a lazy, immutable sequence of ints: constant memory,
            `len`, indexing, slicing and O(1) `in` (1.5.7).
            """
        ),
        code(
            """
            invoice_numbers = range(1000, 2000, 10)
            print(f"{len(invoice_numbers)=}, {invoice_numbers[3]=}, {1500 in invoice_numbers=}")
            print(f"{invoice_numbers[:3]=}, {list(range(5, 0, -2))=}")
            """
        ),
    ]


def _comprehension_cells() -> list[NotebookNode]:
    """1.9.3 Comprehensions."""
    return [
        md(
            """
            ### 1.9.3 Comprehensions

            A comprehension builds a container from an iterable in one expression:

            | Kind | Syntax | Result |
            | --- | --- | --- |
            | List | `[expression for item in iterable if condition]` | `list` |
            | Dict | `{key: value for item in iterable if condition}` | `dict` |
            | Set | `{expression for item in iterable if condition}` | `set` |
            | Generator expression | `(expression for item in iterable)` | lazy iterator (1.13) |

            **List comprehension**, the replacement for `.map()` (and the `append` loop):
            """
        ),
        code(
            """
            prices_in_rupees = [120, 499, 999]
            prices_with_gst = [round(price * 1.18, 2) for price in prices_in_rupees]
            print(f"{prices_with_gst=}")
            """
        ),
        md("**Filters**: an `if` clause keeps only matching items (the `.filter()` part)."),
        code(
            """
            order_totals = [120, 1499, 650, 2300]
            free_shipping_orders = [total for total in order_totals if total >= 999]
            print(f"{free_shipping_orders=}")
            labels = ["big" if total >= 999 else "small" for total in order_totals]
            print(f"{labels=}  (a conditional *expression* in the output part is different)")
            """
        ),
        md("**Dict comprehension**: build a mapping, for example an index or an inverted dict."),
        code(
            """
            product_names = ["tea", "rice", "ghee"]
            name_lengths = {name: len(name) for name in product_names}
            sku_by_name = {"tea": "TEA-500G", "rice": "RICE-5KG"}
            name_by_sku = {sku: name for name, sku in sku_by_name.items()}
            print(f"{name_lengths=}")
            print(f"{name_by_sku=}")
            """
        ),
        md("**Set comprehension**: unique results (printed sorted, see 1.6 on string-set order)."),
        code(
            """
            customer_emails = ["Asha@Mail.in", "asha@mail.in", "ravi@mail.in"]
            unique_emails = {email.lower() for email in customer_emails}
            print(f"{sorted(unique_emails)=}")
            """
        ),
        md(
            """
            **Nested `for` order.** Several `for` clauses read **left to right, outer to inner**,
            exactly like the nested loops they replace:

            ```python
            [cell for row in grid for cell in row]
            # is
            for row in grid:
                for cell in row:
                    result.append(cell)
            ```
            """
        ),
        code(
            """
            sizes, colours = ["S", "M"], ["red", "blue"]
            variants = [f"{size}-{colour}" for size in sizes for colour in colours]
            print(f"{variants=}")

            seat_grid = [[1, 2, 3], [4, 5, 6]]
            flat_seats = [seat for row in seat_grid for seat in row]
            even_seats = [seat for row in seat_grid for seat in row if seat % 2 == 0]
            print(f"{flat_seats=}, {even_seats=}")
            """
        ),
        md(
            """
            **Own scope.** A comprehension's loop variable does **not** leak into the surrounding
            code (a plain `for` loop's variable does). Since Python 3.12 (PEP 709) comprehensions
            are inlined into the enclosing function for speed, but the isolation is kept.
            """
        ),
        code(
            """
            comprehension_item = "before"
            doubled_items = [comprehension_item * 2 for comprehension_item in "ab"]
            print(f"{doubled_items=}, {comprehension_item=}  (unchanged)")

            for loop_item in "ab":  # noqa: B007
                pass
            print(f"{loop_item=}  (a for loop's variable survives the loop)")
            """
        ),
        md(
            """
            #### Under the hood: inlined comprehensions (PEP 709)

            Before 3.12, every comprehension compiled to a hidden function that was created and
            called each time. Now the bytecode sits inline; `LOAD_FAST_AND_CLEAR` saves any
            outer variable with the same name and restores it afterwards, which is how the
            isolation survives. There is no `MAKE_FUNCTION` in the output.
            """
        ),
        code(
            '''
            def doubled(values: list[int]) -> list[int]:
                """Double every value with a comprehension."""
                return [value * 2 for value in values]


            doubled_opnames = [instruction.opname for instruction in dis.get_instructions(doubled)]
            print(f"{'MAKE_FUNCTION' in doubled_opnames=}, {'LOAD_FAST_AND_CLEAR' in doubled_opnames=}")
            '''
        ),
        md(
            """
            **Readability limits.** One `for`, maybe one `if`: a comprehension reads like a
            sentence. With two loops, two conditions and a nested conditional expression it
            stops being readable; a plain loop with names for each step is better. Both versions
            below compute the same result.
            """
        ),
        code(
            '''
            daily_orders = [[120, 1500, -1], [999, 2300], [450]]

            hard_to_read = [
                total * 0.9 if total > 1000 else total
                for day in daily_orders
                for total in day
                if total > 0
                if total != 999
            ]


            def discounted_totals(days: list[list[int]]) -> list[float]:
                """Skip invalid and exact-999 totals; give 10% off totals over 1000."""
                result = []
                for day in days:
                    for total in day:
                        if total <= 0 or total == 999:
                            continue
                        result.append(total * 0.9 if total > 1000 else total)
                return result


            print(f"{hard_to_read == discounted_totals(daily_orders)=}, {hard_to_read=}")
            '''
        ),
    ]


def _catalogue_cells() -> list[NotebookNode]:
    """1.9.4 Built-in functions catalogue: table plus one demo cell per function."""
    return [
        md(
            r"""
            ### 1.9.4 Built-in functions catalogue

            Python has about 70 built-in functions (`import builtins; dir(builtins)`). These are
            the ones you use every day, grouped by purpose. Each gets its own demo cell below,
            under a heading per group.

            | Group | Function | Signature | Example | JS equivalent |
            | --- | --- | --- | --- | --- |
            | Numeric | `abs` | `abs(x)` | `abs(-5)` → `5` | `Math.abs` |
            | Numeric | `round` | `round(number, ndigits=None)` | `round(2.5)` → `2` | `Math.round` (rounds half up) |
            | Numeric | `divmod` | `divmod(a, b)` | `divmod(17, 5)` → `(3, 2)` | — |
            | Numeric | `pow` | `pow(base, exp, mod=None)` | `pow(3, 4, 5)` → `1` | `**`, `Math.pow` |
            | Numeric | `sum` | `sum(iterable, /, start=0)` | `sum([1, 2], start=10)` → `13` | `reduce((a, b) => a + b, 0)` |
            | Numeric | `min` | `min(iterable, *, key=None, default=...)` | `min([], default=0)` → `0` | `Math.min(...a)` |
            | Numeric | `max` | `max(iterable, *, key=None, default=...)` | `max(names, key=len)` | `Math.max(...a)` |
            | Iteration | `len` | `len(obj)` | `len("tea")` → `3` | `.length`, `.size` |
            | Iteration | `iter` | `iter(obj)`, `iter(callable, sentinel)` | `iter([1, 2])` | `a[Symbol.iterator]()` |
            | Iteration | `next` | `next(iterator, default)` | `next(it, None)` | `it.next().value` |
            | Iteration | `map` | `map(function, *iterables, strict=False)` | `map(str.upper, names)` | `a.map(f)` (eager) |
            | Iteration | `filter` | `filter(function, iterable)` | `filter(None, items)` | `a.filter(f)` (eager) |
            | Iteration | `any` | `any(iterable)` | `any(x > 3 for x in a)` | `a.some(f)` |
            | Iteration | `all` | `all(iterable)` | `all([])` → `True` | `a.every(f)` |
            | Iteration | `enumerate` | `enumerate(iterable, start=0)` | `enumerate(a, start=1)` | `a.entries()` |
            | Iteration | `zip` | `zip(*iterables, strict=False)` | `zip(a, b, strict=True)` | lodash `zip` |
            | Iteration | `reversed` | `reversed(sequence)` | `reversed([1, 2])` | `a.toReversed()` |
            | Iteration | `sorted` | `sorted(iterable, *, key=None, reverse=False)` | `sorted(a, key=len)` | `a.toSorted(cmp)` |
            | Conversion | `int` | `int(x=0)`, `int(text, base=10)` | `int("ff", 16)` → `255` | `parseInt(s, 16)` |
            | Conversion | `float` | `float(x=0.0)` | `float("1e3")` → `1000.0` | `parseFloat`, `Number` |
            | Conversion | `str` | `str(object="")` | `str(42)` → `'42'` | `String(x)` |
            | Conversion | `bool` | `bool(x=False)` | `bool([])` → `False` | `Boolean(x)` |
            | Conversion | `list` | `list(iterable=())` | `list("ab")` → `['a', 'b']` | `Array.from` |
            | Conversion | `tuple` | `tuple(iterable=())` | `tuple([1, 2])` → `(1, 2)` | — |
            | Conversion | `dict` | `dict(mapping_or_pairs, **kwargs)` | `dict(a=1)` → `{'a': 1}` | `Object.fromEntries` |
            | Conversion | `set` | `set(iterable=())` | `set("aab")` → `{'a', 'b'}` | `new Set(a)` |
            | Conversion | `frozenset` | `frozenset(iterable=())` | `frozenset({1, 2})` | — |
            | Conversion | `bytes` | `bytes(source, encoding)` | `bytes("₹", "utf-8")` | `new TextEncoder().encode` |
            | Conversion | `chr` | `chr(code_point)` | `chr(8377)` → `'₹'` | `String.fromCodePoint` |
            | Conversion | `ord` | `ord(character)` | `ord("A")` → `65` | `s.codePointAt(0)` |
            | Conversion | `bin` | `bin(integer)` | `bin(5)` → `'0b101'` | `n.toString(2)` |
            | Conversion | `hex` | `hex(integer)` | `hex(255)` → `'0xff'` | `n.toString(16)` |
            | Conversion | `oct` | `oct(integer)` | `oct(8)` → `'0o10'` | `n.toString(8)` |
            | Conversion | `format` | `format(value, format_spec="")` | `format(0.25, ".0%")` → `'25%'` | `Intl.NumberFormat` |
            | Conversion | `repr` | `repr(object)` | `repr("tea")` → `"'tea'"` | `JSON.stringify` (roughly) |
            | Conversion | `ascii` | `ascii(object)` | `ascii("₹")` → `"'\u20b9'"` | — |
            | Introspection | `type` | `type(obj)`, `type(name, bases, namespace)` | `type(3)` → `int` | `typeof` |
            | Introspection | `isinstance` | `isinstance(obj, class_or_tuple)` | `isinstance(3, int \| float)` | `instanceof` |
            | Introspection | `issubclass` | `issubclass(cls, class_or_tuple)` | `issubclass(bool, int)` → `True` | `C.prototype instanceof B` |
            | Introspection | `id` | `id(obj)` | `id(a) == id(b)` | — |
            | Introspection | `hash` | `hash(obj)` | `hash(1) == hash(1.0)` | — |
            | Introspection | `callable` | `callable(obj)` | `callable(len)` → `True` | `typeof f === "function"` |
            | Introspection | `dir` | `dir(obj)` | `dir("")` | `Object.getOwnPropertyNames` |
            | Introspection | `vars` | `vars(obj)` | `vars(instance)` | (the object itself) |
            | Introspection | `globals` | `globals()` | `"x" in globals()` | `globalThis` |
            | Introspection | `locals` | `locals()` | `locals()` in a function | — |
            | Introspection | `getattr` | `getattr(obj, name, default)` | `getattr(o, "x", 0)` | `o[name] ?? 0` |
            | Introspection | `setattr` | `setattr(obj, name, value)` | `setattr(o, "x", 1)` | `o[name] = 1` |
            | Introspection | `hasattr` | `hasattr(obj, name)` | `hasattr(o, "x")` | `name in o` |
            | Introspection | `delattr` | `delattr(obj, name)` | `delattr(o, "x")` | `delete o[name]` |
            | Introspection | `help` | `help(obj)` | `help(divmod)` | — (MDN) |
            | I/O | `print` | `print(*objects, sep=" ", end="\n", file=None, flush=False)` | `print(a, b, sep=", ")` | `console.log` |
            | I/O | `input` | `input(prompt="")` | `input("Name: ")` | `prompt()` / `readline` |
            | I/O | `open` | `open(file, mode="r", encoding=None, ...)` | `open(p, encoding="utf-8")` | `fs.readFileSync` |
            | Dangerous | `eval` | `eval(expression, globals=None, locals=None)` | `eval("2 + 3")` → `5` | `eval` |
            | Dangerous | `exec` | `exec(source, globals=None, locals=None)` | `exec("x = 1", namespace)` | `new Function(...)()` |
            | Dangerous | `compile` | `compile(source, filename, mode)` | `compile("x * 2", "<rule>", "eval")` | `new Function` |
            | Safe alternative | `ast.literal_eval` | `ast.literal_eval(text)` | `literal_eval("[1, 2]")` | `JSON.parse` |

            #### Numeric

            **`abs(x)`**: absolute value; for a complex number, its magnitude. Works on any type
            with `__abs__` (`Decimal`, `Fraction`).
            """
        ),
        code(
            """
            print(f"{abs(-5)=}, {abs(-2.5)=}, {abs(3 + 4j)=}, {abs(Decimal('-19.99'))=}")
            """
        ),
        md(
            """
            **`round(number, ndigits=None)`**: without `ndigits` it returns an `int`. Ties go to
            the **even** neighbour (banker's rounding), unlike JavaScript's `Math.round`. Some
            "ties" are not ties at all: `2.675` is stored as `2.67499999…` (1.3.2), so money
            should use `Decimal.quantize` instead.
            """
        ),
        code(
            """
            print(f"{round(2.5)=}, {round(3.5)=}, {round(-0.5)=}  (ties to even)")
            print(f"{round(3.14159, 2)=}, {round(1234, -2)=}, {type(round(2.7)).__name__=}")
            print(f"{round(2.675, 2)=}  (2.675 is really 2.67499999...)")
            """
        ),
        md("**`divmod(a, b)`**: `(a // b, a % b)` in one call, handy for unit conversions."),
        code(
            """
            total_seconds = 3725
            minutes, seconds = divmod(total_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            print(f"{hours}h {minutes}m {seconds}s, {divmod(-7, 2)=}")
            """
        ),
        md(
            """
            **`pow(base, exp, mod=None)`**: like `**`, plus a fast three-argument form for
            modular arithmetic (`pow(base, -1, mod)` is the modular inverse, 3.8).
            """
        ),
        code(
            """
            print(f"{pow(2, 10)=}, {pow(2, -1)=}, {pow(3, 4, 5)=}")
            print(f"{pow(38, -1, 97)=}, {38 * pow(38, -1, 97) % 97=}")
            """
        ),
        md(
            """
            **`sum(iterable, /, start=0)`**: adds numbers. `start` is the initial value: it sets
            the result for an empty input and its type (here `Decimal("0.00")` keeps money as
            `Decimal`). `sum` refuses strings; use `"".join(...)`.
            """
        ),
        code(
            """
            line_totals = [Decimal("498.00"), Decimal("640.00")]
            print(f"{sum(line_totals)=}, {sum([], start=Decimal('0.00'))=}, {sum([])=}")
            print(f"{sum([1, 2, 3], start=10)=}")
            print(f"strings: {raised_error_name(lambda: sum(['a', 'b'], start=''))}")
            """
        ),
        md(
            """
            **`min(iterable, *, key=None, default=...)`** (or `min(a, b, ...)`): the smallest
            item. `key` compares by a derived value and returns the original item; `default` is
            returned for an empty iterable instead of raising `ValueError`.
            """
        ),
        code(
            """
            stock_levels = {"tea": 5, "rice": 12, "ghee": 2}
            print(f"{min(4, 9, 1)=}, {min(stock_levels, key=stock_levels.get)=}")
            print(f"{min([], default=None)=}, empty: {raised_error_name(lambda: min([]))}")
            """
        ),
        md(
            "**`max(iterable, *, key=None, default=...)`**: the largest item; on ties, the **first** one wins."
        ),
        code(
            """
            product_names = ["tea", "rice", "ghee"]
            print(f"{max(product_names, key=len)=}  (rice and ghee tie: first wins)")
            print(f"{max([], default=0)=}, {max('apple', 'banana')=}")
            """
        ),
        md(
            """
            #### Iteration

            **`len(obj)`**: the number of items, from `__len__`. O(1) for built-in containers.
            Iterators and generators have no length.
            """
        ),
        code(
            """
            print(f"{len('₹99')=}, {len([1, 2])=}, {len({'a': 1})=}, {len(range(0, 10, 3))=}")
            print(f"generator: {raised_error_name(lambda: len(n for n in range(3)))}")
            """
        ),
        md(
            "**`iter(obj)` / `iter(callable, sentinel)`**: get an iterator (1.9.1); a non-iterable raises `TypeError`."
        ),
        code(
            """
            letter_iterator = iter("ab")
            print(f"{next(letter_iterator)=}, {iter(letter_iterator) is letter_iterator=}")
            print(f"iter(5): {raised_error_name(lambda: iter(5))}")
            """
        ),
        md(
            """
            **`next(iterator, default)`**: the next item; with a default, it returns that instead
            of raising `StopIteration`. `next(generator, None)` is the idiom for "first match or
            None".
            """
        ),
        code(
            """
            order_totals = [120, 1499, 650]
            first_large = next((total for total in order_totals if total > 1000), None)
            first_huge = next((total for total in order_totals if total > 5000), None)
            print(f"{first_large=}, {first_huge=}")
            """
        ),
        md(
            """
            **`map(function, *iterables, strict=False)`**: a lazy iterator of `function(item)`.
            With several iterables it calls `function(a, b)`. `strict=True` is *New in 3.14*
            (same meaning as in `zip`).
            """
        ),
        code(
            """
            print(f"{list(map(str.upper, ['tea', 'rice']))=}")
            print(f"{list(map(operator.mul, [249, 525], [2, 1]))=}")  # noqa: B912
            if sys.version_info >= (3, 14):
                print(f"strict: {raised_error_name(lambda: list(map(pow, [2, 3], [3], strict=True)))}")
            else:
                print("map(strict=True) needs Python 3.14; skipped")
            """
        ),
        md(
            "**`filter(function, iterable)`**: a lazy iterator of items where `function(item)` is truthy; `filter(None, ...)` keeps truthy items."
        ),
        code(
            """
            raw_tags = ["new", "", "sale", None, "organic"]
            print(f"{list(filter(None, raw_tags))=}")
            print(f"{list(filter(str.isdigit, ['12', 'ab', '7']))=}")
            """
        ),
        md(
            "**`any(iterable)`**: `True` if any item is truthy; stops at the first one. `any([])` is `False`."
        ),
        code(
            """
            days_overdue = [0, 3, 45, 2]
            print(f"{any(days > 30 for days in days_overdue)=}, {any([])=}")
            """
        ),
        md(
            "**`all(iterable)`**: `True` if every item is truthy; stops at the first falsy one. `all([])` is `True` (nothing fails)."
        ),
        code(
            """
            required_fields = {"name": "Asha", "email": "asha@mail.in", "phone": ""}
            print(f"{all(required_fields.values())=}, {all([])=}")
            """
        ),
        md("**`enumerate(iterable, start=0)`**: `(index, item)` pairs (1.9.2)."),
        code(
            """
            print(f"{list(enumerate(['tea', 'rice'], start=1))=}")
            """
        ),
        md("**`zip(*iterables, strict=False)`**: tuples of parallel items (1.9.2)."),
        code(
            """
            print(f"{dict(zip(['tea', 'rice'], [249, 525], strict=True))=}")
            """
        ),
        md("**`reversed(sequence)`**: a reverse iterator, no copy (1.9.2)."),
        code(
            """
            print(f"{list(reversed(['v1', 'v2', 'v3']))=}")
            """
        ),
        md("**`sorted(iterable, *, key=None, reverse=False)`**: a new sorted list (1.9.2, 1.5.4)."),
        code(
            """
            print(f"{sorted(['Rice', 'tea', 'Ghee'], key=str.casefold)=}")
            """
        ),
        md(
            """
            #### Conversion

            **`int(x)` / `int(text, base=10)`**: from a float it truncates toward zero; from text
            it accepts surrounding whitespace and `_` separators, but not a decimal point.
            """
        ),
        code(
            """
            print(f"{int('42')=}, {int(' 7 ')=}, {int('1_000')=}, {int('ff', 16)=}, {int('0b101', 0)=}")
            print(f"{int(3.9)=}, {int(-3.9)=}  (truncates toward zero)")
            print(f"int('3.5'): {raised_error_name(lambda: int('3.5'))}")
            """
        ),
        md("**`float(x)`**: parses decimal and scientific notation, `'nan'` and `'inf'`."),
        code(
            """
            print(f"{float('1e3')=}, {float(' 2.5 ')=}, {float('inf')=}, {float('nan')=}")
            print(f"float('1,5'): {raised_error_name(lambda: float('1,5'))}")
            """
        ),
        md(
            "**`str(object)`**: the readable text form (`__str__`). Trap: `str(b'x')` gives `\"b'x'\"`; decode bytes instead."
        ),
        code(
            """
            print(f"{str(42)=}, {str(None)=}, {str(['tea'])=}")
            print(f"{str(b'tea')=}  vs  {b'tea'.decode('utf-8')=}")
            """
        ),
        md(
            "**`bool(x)`**: truthiness (1.3.8). Trap: any non-empty string is `True`, including `'False'`."
        ),
        code(
            """
            print(f"{bool(0)=}, {bool([])=}, {bool('False')=}, {bool('0')=}")
            """
        ),
        md("**`list(iterable)`**: a new list from any iterable."),
        code(
            """
            print(f"{list('UPI')=}, {list(range(3))=}, {list({'a': 1, 'b': 2})=}")
            """
        ),
        md("**`tuple(iterable)`**: a new tuple (an immutable snapshot, 1.7.7)."),
        code(
            """
            print(f"{tuple(['tea', 'rice'])=}, {tuple('ab')=}")
            """
        ),
        md(
            "**`dict(mapping_or_pairs, **kwargs)`**: from a mapping, from `(key, value)` pairs, or from keywords."
        ),
        code(
            """
            print(f"{dict([('tea', 249), ('rice', 525)])=}")
            print(f"{dict(tea=249, rice=525)=}, {dict({'tea': 249}, ghee=640)=}")
            """
        ),
        md("**`set(iterable)`**: unique elements (`set()` is the only way to write an empty set)."),
        code(
            """
            print(f"{sorted(set('banana'))=}, {set()=}, {type({}).__name__=}")
            """
        ),
        md("**`frozenset(iterable)`**: an immutable, hashable set."),
        code(
            """
            weekend_days = frozenset({"sat", "sun"})
            print(f"{sorted(weekend_days)=}, {hash(weekend_days) == hash(frozenset({'sun', 'sat'}))=}")
            """
        ),
        md(
            "**`bytes(source, encoding)`**: encode text, zero-fill a size, or copy a list of ints 0–255."
        ),
        code(
            """
            print(f"{bytes('₹99', 'utf-8')=}, {bytes(3)=}, {bytes([72, 105])=}")
            """
        ),
        md("**`chr(code_point)`**: the character for a Unicode code point."),
        code(
            """
            print(f"{chr(65)=}, {chr(8377)=}, {chr(0x1F600)=}")
            """
        ),
        md("**`ord(character)`**: the code point of a single character."),
        code(
            """
            print(f"{ord('A')=}, {ord('₹')=}, {hex(ord('₹'))=}")
            print(f"ord('ab'): {raised_error_name(lambda: ord('ab'))}")
            """
        ),
        md("**`bin(integer)`**: binary text with a `0b` prefix (`format(n, 'b')` drops it)."),
        code(
            """
            print(f"{bin(10)=}, {bin(-10)=}, {format(10, '08b')=}")
            """
        ),
        md("**`hex(integer)`**: hexadecimal text with a `0x` prefix."),
        code(
            """
            print(f"{hex(255)=}, {hex(8377)=}, {format(255, 'X')=}")
            """
        ),
        md("**`oct(integer)`**: octal text with a `0o` prefix (Unix file permissions are octal)."),
        code(
            """
            print(f"{oct(8)=}, {oct(0o755)=}, {0o755 == 493=}")
            """
        ),
        md(
            "**`format(value, format_spec)`**: the format-spec mini-language of f-strings (1.4.3), as a function."
        ),
        code(
            """
            print(f"{format(1234567.891, ',.2f')=}, {format(0.25, '.0%')=}, {format(42, '>6')=}")
            """
        ),
        md(
            "**`repr(object)`**: the unambiguous developer form (`__repr__`); for built-ins, valid Python that recreates the value."
        ),
        code(
            """
            price_text = "249"
            print(f"{str(price_text)=}, {repr(price_text)=}")
            print(f"{eval(repr([1, 'two', None])) == [1, 'two', None]=}")
            """
        ),
        md("**`ascii(object)`**: like `repr`, but non-ASCII characters are escaped."),
        code(
            """
            print(f"{ascii('₹99 café')=}")
            """
        ),
        md(
            """
            #### Introspection

            **`type(obj)`**: the class of an object. The rarely used three-argument form
            `type(name, bases, namespace)` creates a new class at run time (Phase 2 covers
            metaclasses).
            """
        ),
        code(
            """
            sample_quantity, sample_name = 3, "tea"
            print(f"{type(sample_quantity)=}, {type(sample_name).__name__=}, {type(type)=}")
            DynamicProduct = type("DynamicProduct", (), {"currency": "INR"})
            print(f"{DynamicProduct.__name__=}, {DynamicProduct().currency=}")
            """
        ),
        md(
            """
            **`isinstance(obj, class_or_tuple)`**: also true for subclasses. Accepts a tuple or a
            `X | Y` union (3.10). `bool` is a subclass of `int`, a classic surprise.
            """
        ),
        code(
            """
            print(f"{isinstance(3, int)=}, {isinstance(3.0, int | float)=}, {isinstance('3', (int, float))=}")
            print(f"{isinstance(True, int)=}  (bool subclasses int)")
            """
        ),
        md("**`issubclass(cls, class_or_tuple)`**: the same test for classes."),
        code(
            """
            print(f"{issubclass(bool, int)=}, {issubclass(int, object)=}, {issubclass(str, int)=}")
            """
        ),
        md(
            "**`id(obj)`**: an integer unique among objects alive at the same time (the address in CPython). Compare ids; never store or print them as data."
        ),
        code(
            """
            first_cart = ["tea"]
            second_cart = first_cart
            print(f"{id(first_cart) == id(second_cart)=}, {id(first_cart) == id(['tea'])=}")
            """
        ),
        md(
            "**`hash(obj)`**: the hash used by dicts and sets (1.6.2); equal objects have equal hashes; mutable built-ins have none."
        ),
        code(
            """
            print(f"{hash(1) == hash(1.0) == hash(True)=}, {hash((1, 2)) == hash((1, 2))=}")
            print(f"hash([]): {raised_error_name(lambda: hash([]))}")
            """
        ),
        md("**`callable(obj)`**: `True` for functions, classes and objects with `__call__`."),
        code(
            """
            print(f"{callable(len)=}, {callable(str)=}, {callable('len')=}, {callable(lambda: 0)=}")
            """
        ),
        md(
            "**`dir(obj)`**: the attribute names an object has (sorted), including dunders; filter them for a quick API overview."
        ),
        code(
            """
            public_str_methods = [name for name in dir(str) if not name.startswith("_")]
            print(f"{len(public_str_methods)=}, {public_str_methods[:6]=}")
            """
        ),
        md(
            "**`vars(obj)`**: the object's `__dict__` (its attributes as a dict); works for instances, classes and modules."
        ),
        code(
            '''
            class Customer:
                """A small class for the attribute built-ins."""

                def __init__(self, name: str, city: str) -> None:
                    self.name = name
                    self.city = city


            asha = Customer("Asha", "Pune")
            print(f"{vars(asha)=}, {vars(asha) is asha.__dict__=}")
            '''
        ),
        md(
            "**`globals()`**: the current module's namespace dict. In a notebook, that is every name defined so far."
        ),
        code(
            """
            print(f"{'Customer' in globals()=}, {type(globals()).__name__=}")
            print(f"{globals()['asha'] is asha=}")
            """
        ),
        md(
            """
            **`locals()`**: the local names of the current function. *Changed in 3.13* (PEP 667):
            inside a function it returns a **fresh snapshot** on every call, so later
            assignments do not show up in an earlier result, and writing to it never changes a
            variable.
            """
        ),
        code(
            '''
            def checkout_summary(order_total: int) -> None:
                """Show locals() as a snapshot."""
                delivery_fee = 40
                snapshot = locals()
                delivery_fee = 0
                print(f"{snapshot=}")
                print(f"{locals()['delivery_fee']=}  (a new snapshot sees the change)")


            checkout_summary(1200)
            '''
        ),
        md(
            """
            **`getattr(obj, name, default)`**: read an attribute whose name is only known at run
            time (from a column header, a config file, a request). With a literal name, just
            write `obj.name`. The default avoids `AttributeError`.
            """
        ),
        code(
            """
            for field_name in ("city", "phone"):
                print(f"{field_name}: {getattr(asha, field_name, 'not given')}")
            missing_field = "phone"
            print(f"no default: {raised_error_name(lambda: getattr(asha, missing_field))}")
            """
        ),
        md(
            "**`setattr(obj, name, value)`**: assign an attribute by name, for example from a dict of updates."
        ),
        code(
            """
            profile_updates = {"city": "Mumbai", "phone": "98200 00000"}
            for field_name, new_value in profile_updates.items():
                setattr(asha, field_name, new_value)
            print(f"{vars(asha)=}")
            """
        ),
        md("**`hasattr(obj, name)`**: `True` if `getattr` would succeed."),
        code(
            """
            print(f"{hasattr(asha, 'name')=}, {hasattr(asha, 'email')=}, {hasattr('tea', 'upper')=}")
            """
        ),
        md("**`delattr(obj, name)`**: delete an attribute by name (`del obj.name`)."),
        code(
            """
            for field_name in ("city", "phone"):
                delattr(asha, field_name)
            print(f"{vars(asha)=}, {hasattr(asha, 'city')=}")
            """
        ),
        md(
            "**`help(obj)`**: prints the signature and docstring (1.10.8 writes docstrings that `help` can show)."
        ),
        code(
            """
            help(divmod)
            """
        ),
        md(
            """
            #### I/O

            **`print(*objects, sep=" ", end="\\n", file=None, flush=False)`**: `sep` goes between
            objects, `end` after the last one, `file` redirects the output (any object with
            `write`), and `flush=True` pushes it out immediately (progress output, logs).
            """
        ),
        code(
            """
            print("tea", "rice", "ghee", sep=" | ")
            print("loading", end="... ")
            print("done")
            report_buffer = io.StringIO()
            print("total", 1498, sep="=", file=report_buffer, flush=True)
            print(f"{report_buffer.getvalue()=}")
            """
        ),
        md(
            """
            **`input(prompt="")`**: prints the prompt and reads one line from standard input,
            **without** the newline, always as a `str`. A notebook run headless has no keyboard,
            so the demo starts a child interpreter and feeds its standard input.
            """
        ),
        code(
            """
            child_code = 'name = input("Name: "); qty = int(input("Qty: ")); print(f"|{name}|{qty * 2}|")'
            completed = subprocess.run(
                [sys.executable, "-c", child_code],
                input="Asha\\n3\\n",
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"{completed.stdout=}")
            """
        ),
        md(
            """
            **`open(file, mode="r", encoding=None, ...)`**: open a file. Always pass
            `encoding="utf-8"` for text, and use `with` so the file is closed (1.14). Modes:
            `"r"`, `"w"` (truncate), `"a"` (append), `"x"` (create only), plus `"b"` for bytes.
            """
        ),
        code(
            """
            receipt_path = scratch_dir / "unit_1_9_receipt.txt"
            with open(receipt_path, "w", encoding="utf-8") as receipt_file:
                receipt_file.write("tea 2 x ₹249\\n")
                receipt_file.write("ghee 1 x ₹640\\n")
            with open(receipt_path, encoding="utf-8") as receipt_file:
                receipt_lines = [line.rstrip() for line in receipt_file]
            print(f"{receipt_lines=}, {receipt_file.closed=}")
            """
        ),
        md(
            """
            #### Dangerous

            > **Warning:** `eval`, `exec` and `compile` run arbitrary code. Never pass them text
            > that came from a user, a file or the network. Restricting `globals` does **not**
            > make them safe.

            **`eval(expression, globals=None, locals=None)`**: evaluates one expression and returns
            its value. The cell shows why it is dangerous: an "expression" can import modules,
            and an empty `__builtins__` can still be escaped through the object graph.
            """
        ),
        code(
            """
            print(f"{eval('2 + 3 * 4')=}, {eval('unit_price * 2', {'unit_price': 249})=}")
            sneaky_input = "__import__('os').getcwd()"
            print(f"{type(eval(sneaky_input)).__name__=}  (it imported os and ran a function)")
            escape_route = "().__class__.__mro__[1].__subclasses__()"
            reachable_classes = eval(escape_route, {"__builtins__": {}})
            print(f"{len(reachable_classes) > 100=}  (every loaded class is reachable without builtins)")
            """
        ),
        md(
            "**`exec(source, globals=None, locals=None)`**: runs statements; returns `None`. Pass a dict to keep the names it defines out of your namespace."
        ),
        code(
            """
            plugin_namespace: dict[str, Any] = {}
            exec_result = exec("def bonus(total):\\n    return total // 10", plugin_namespace)
            print(f"{exec_result=}, {plugin_namespace['bonus'](1500)=}")
            """
        ),
        md(
            """
            **`compile(source, filename, mode)`**: turns source into a code object without running
            it. Modes: `"eval"` (one expression), `"exec"` (statements), `"single"` (one
            interactive statement). Compiling once and evaluating many times avoids re-parsing.
            """
        ),
        code(
            """
            discount_rule = compile("total * 0.9 if total > 1000 else total", "<discount-rule>", "eval")
            print(f"{type(discount_rule).__name__=}, {discount_rule.co_filename=}")
            print([eval(discount_rule, {"total": total}) for total in (500, 2000)])
            """
        ),
        md(
            """
            **`ast.literal_eval(text)`**: the **safe** alternative for data. It parses only Python
            literals (strings, bytes, numbers, tuples, lists, dicts, sets, booleans, `None`) and
            rejects everything else, including names and calls. For JSON text, use `json.loads`.
            """
        ),
        code(
            """
            saved_settings = "{'currency': 'INR', 'tiers': (499, 999), 'beta': None}"
            print(f"{ast.literal_eval(saved_settings)=}")
            print(f"call: {raised_error_name(lambda: ast.literal_eval(sneaky_input))}")
            print(f"name: {raised_error_name(lambda: ast.literal_eval('unit_price * 2'))}")
            """
        ),
    ]


def _map_filter_cells() -> list[NotebookNode]:
    """1.9.5 map / filter vs comprehensions."""
    return [
        md(
            """
            ### 1.9.5 `map` / `filter` vs comprehensions

            | | `map` / `filter` | List comprehension |
            | --- | --- | --- |
            | Result | lazy iterator | list, built immediately |
            | Reusable | no: one pass | yes |
            | Reads well when | applying an **existing** named function | any expression, with a filter |
            | Needs `lambda` for an expression | yes | no |

            **Laziness**: `map` does no work until something consumes it. The `loud_gst`
            function prints when it runs, so you can see when the work happens.
            """
        ),
        code(
            '''
            def loud_gst(price: int) -> float:
                """Add 18% GST and print that the work happened."""
                print(f"  computing GST for {price}")
                return round(price * 1.18, 2)


            lazy_prices = map(loud_gst, [100, 200])
            print("map created, nothing computed yet")
            print(f"{next(lazy_prices)=}")
            print("comprehension:")
            eager_prices = [loud_gst(price) for price in [100, 200]]
            '''
        ),
        md(
            """
            **Single use**: a `map` / `filter` object is an iterator, so a second pass finds it
            empty, silently. Convert with `list()` if you need the values twice.
            """
        ),
        code(
            """
            valid_quantities = filter(lambda quantity: quantity > 0, [3, 0, 2])
            print(f"{sum(valid_quantities)=}")
            print(f"{sum(valid_quantities)=}  (already consumed)")
            """
        ),
        md(
            """
            **Readability**: with an existing function, `map` is short and clear. With a `lambda`
            and a `filter`, the comprehension wins.
            """
        ),
        code(
            """
            product_names = ["tea", "rice", "ghee"]
            prices_in_rupees = [80, 249, 640, 1500]
            print(f"{list(map(str.title, product_names))=}  (fine)")
            with_lambdas = list(
                map(lambda price: price * 2, filter(lambda price: price > 200, prices_in_rupees))
            )
            with_comprehension = [price * 2 for price in prices_in_rupees if price > 200]
            print(f"{with_lambdas == with_comprehension=}, {with_comprehension=}")
            """
        ),
        md(
            """
            **Timing**: loop + `append` vs comprehension vs `map` with a built-in vs `map` with a
            `lambda`. Comprehensions beat the explicit loop (no method lookup per item); `map`
            with a C function such as `str.upper` is fastest; `map` with a `lambda` loses its edge
            because each item pays for a Python function call.

            > **Note:** timings vary by machine and Python version.
            """
        ),
        code(
            '''
            sample_words = ["tea", "rice", "ghee", "dal"] * 2_500


            def upper_with_loop() -> list[str]:
                """Uppercase with an explicit loop."""
                result = []
                for word in sample_words:
                    result.append(word.upper())
                return result


            timing_candidates = {
                "loop + append": upper_with_loop,
                "comprehension": lambda: [word.upper() for word in sample_words],
                "map(str.upper)": lambda: list(map(str.upper, sample_words)),
                "map(lambda)": lambda: list(map(lambda word: word.upper(), sample_words)),
            }
            for label, candidate in timing_candidates.items():
                seconds = min(timeit.repeat(candidate, number=50, repeat=3)) / 50
                print(f"{label:15} {seconds * 1e6:8.1f} µs per 10 000 words")
            '''
        ),
        *predict_cells(
            snippet="""
            quantities = map(int, ["10", "20", "30"])
            print(sum(quantities), sum(quantities))
            print(any([]), all([]))
            """,
            answer="""
            `60 0` then `False True`. The first `sum` consumes the `map` iterator, so the second
            sum sees no items and returns its start value `0`. `any([])` has no truthy item;
            `all([])` has no falsy item, so it is vacuously `True`.
            """,
            proof="""
            quantities = map(int, ["10", "20", "30"])
            print(sum(quantities), sum(quantities))
            print(any([]), all([]))
            """,
        ),
    ]


def _idiom_cells() -> list[NotebookNode]:
    """1.9.6 Pythonic idioms."""
    return [
        md(
            """
            ### 1.9.6 Pythonic idioms

            Each pair below does the same work: first the style that comes over from C or
            JavaScript, then the Python idiom.

            **`enumerate` over `range(len())`**: you need the index *and* the item.
            """
        ),
        code(
            """
            queue_names = ["asha", "ravi", "meena"]
            for position in range(len(queue_names)):  # un-Pythonic
                print(f"{position}: {queue_names[position]}", end="  ")
            print()
            for position, queue_name in enumerate(queue_names):  # idiomatic
                print(f"{position}: {queue_name}", end="  ")
            print()
            """
        ),
        md("**`zip` over parallel indexing**: walk two sequences together."),
        code(
            """
            cities = ["Pune", "Delhi"]
            temperatures = [31, 38]
            for index in range(len(cities)):  # un-Pythonic
                print(f"{cities[index]}: {temperatures[index]}°C", end="  ")
            print()
            for city, temperature in zip(cities, temperatures, strict=True):  # idiomatic
                print(f"{city}: {temperature}°C", end="  ")
            print()
            """
        ),
        md("**`in`** instead of a search loop or a chain of `==` comparisons."),
        code(
            """
            payment_method = "upi"
            is_instant_long = payment_method == "upi" or payment_method == "card" or payment_method == "wallet"
            is_instant = payment_method in {"upi", "card", "wallet"}
            print(f"{is_instant_long=}, {is_instant=}")
            """
        ),
        md("**`any` / `all`** instead of a flag variable and `break`."),
        code(
            """
            stock_levels = [5, 0, 12]
            has_sold_out = False  # un-Pythonic
            for stock in stock_levels:
                if stock == 0:
                    has_sold_out = True
                    break
            print(f"{has_sold_out=}, {any(stock == 0 for stock in stock_levels)=}")
            print(f"{all(stock > 0 for stock in stock_levels)=}")
            """
        ),
        md("**`dict.get`** instead of checking the key first."),
        code(
            """
            discount_by_code = {"WELCOME10": 10, "FESTIVE20": 20}
            entered_code = "SUMMER5"
            if entered_code in discount_by_code:  # un-Pythonic
                discount_percent = discount_by_code[entered_code]
            else:
                discount_percent = 0
            print(f"{discount_percent=}, {discount_by_code.get(entered_code, 0)=}")
            """
        ),
        md(
            """
            **EAFP preview** ("easier to ask forgiveness than permission"): try the operation and
            handle the failure, instead of checking every precondition first (LBYL, "look before
            you leap"). It avoids a race between the check and the use, and the check is not
            done twice. Unit 1.14 covers exceptions in depth.
            """
        ),
        code(
            '''
            def parse_quantity_lbyl(text: str) -> int | None:
                """Look before you leap: check, then convert."""
                if text.strip().isdigit():
                    return int(text)
                return None


            def parse_quantity_eafp(text: str) -> int | None:
                """Easier to ask forgiveness: convert, handle the failure."""
                try:
                    return int(text)
                except ValueError:
                    return None


            for raw_quantity in ("3", " 4 ", "-2", "two"):
                print(
                    f"{raw_quantity!r:6} LBYL={parse_quantity_lbyl(raw_quantity)}, "
                    f"EAFP={parse_quantity_eafp(raw_quantity)}"
                )
            '''
        ),
        md(
            """
            Note the difference for `"-2"`: `isdigit` does not accept a sign, so the LBYL version
            rejects a value that `int` parses fine. Checks written by hand tend to drift from what
            the operation really accepts.
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.9."""
    return [
        md(
            """
            ### Lab 1.9

            Three exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `read_in_chunks(stream, size)`

            Return an **iterator** over chunks of at most `size` characters (text stream) or bytes
            (binary stream), built with `iter(callable, sentinel)`: no `while` loop and no
            generator. It must work for both kinds of stream.

            - Hint: `stream.read(0)` returns the empty value of the right type (`""` or `b""`).
            - Raise `ValueError` immediately if `size < 1`.
            - Read lazily: nothing is read until the first `next()`.
            """
        ),
        code(
            '''
            def read_in_chunks(stream: IO[Any], size: int) -> Iterator[Any]:
                """Return an iterator of chunks of at most size items from stream."""
                raise NotImplementedError("Lab 1.9: implement read_in_chunks()")
            '''
        ),
        md(
            """
            The check cell uses in-memory streams. `reads_lazily()` checks that the stream
            position moves only when a chunk is requested.
            """
        ),
        code(
            '''
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


            run_checks(
                [
                    (
                        "text chunks",
                        lambda: list(read_in_chunks(io.StringIO("abcdefgh"), 3)),
                        ["abc", "def", "gh"],
                    ),
                    (
                        "binary chunks",
                        lambda: list(read_in_chunks(io.BytesIO(b"\\x00\\x01\\x02\\x03"), 2)),
                        [b"\\x00\\x01", b"\\x02\\x03"],
                    ),
                    ("empty stream", lambda: list(read_in_chunks(io.StringIO(""), 4)), []),
                    ("size larger than data", lambda: list(read_in_chunks(io.BytesIO(b"hi"), 100)), [b"hi"]),
                    ("returns an iterator", returns_an_iterator, True),
                    ("reads lazily", reads_lazily, [0, 3]),
                    (
                        "size 0 raises",
                        lambda: raised_error_name(lambda: read_in_chunks(io.StringIO("x"), 0)),
                        "ValueError",
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — rewrite five un-Pythonic loops

            The next cell defines five working but un-Pythonic functions. Write the idiomatic
            versions (same names without `_unpythonic`) using the tools from 1.9.2–1.9.6:

            | Function | Use |
            | --- | --- |
            | `numbered_lines(lines)` | `enumerate(..., start=1)` and a comprehension |
            | `line_totals(unit_prices, quantities)` | `zip(..., strict=True)`: different lengths must raise `ValueError` |
            | `has_overdue(days_overdue)` | `any(...)` |
            | `count_statuses(statuses)` | `dict.get` or `collections.Counter` |
            | `even_squares(numbers)` | a comprehension with a filter |

            The checks compare your versions with the originals; they cannot judge style, so
            compare with the reference solution afterwards.
            """
        ),
        code(
            '''
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
            '''
        ),
        md("The five stubs:"),
        code(
            '''
            def numbered_lines(lines: list[str]) -> list[str]:
                """Number lines from 1 (enumerate)."""
                raise NotImplementedError("Lab 1.9: implement numbered_lines()")


            def line_totals(unit_prices: list[int], quantities: list[int]) -> list[int]:
                """Multiply parallel lists (zip, strict)."""
                raise NotImplementedError("Lab 1.9: implement line_totals()")


            def has_overdue(days_overdue: list[int]) -> bool:
                """Return True if any invoice is more than 30 days overdue (any)."""
                raise NotImplementedError("Lab 1.9: implement has_overdue()")


            def count_statuses(statuses: list[str]) -> dict[str, int]:
                """Count how often each status occurs (dict.get or Counter)."""
                raise NotImplementedError("Lab 1.9: implement count_statuses()")


            def even_squares(numbers: list[int]) -> list[int]:
                """Square the even numbers (comprehension)."""
                raise NotImplementedError("Lab 1.9: implement even_squares()")
            '''
        ),
        md("The check cell runs each pair on the same inputs."),
        code(
            """
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
            """
        ),
        md(
            """
            #### Exercise 3 — summarize webhook events

            Write `summarize_webhooks(events)` returning a dict with exactly these keys, using
            `sum`, `max` and `sorted` (no explicit loops needed):

            | Key | Value |
            | --- | --- |
            | `"event_count"` | number of events |
            | `"captured_total"` | sum of `amount` (paise) over `"payment.captured"` events; `0` if none |
            | `"largest_event_id"` | `event_id` of the event with the largest `amount`; first one on ties; `None` for no events |
            | `"ids_by_time"` | event ids sorted by `received_at` (oldest first) |
            | `"event_types"` | the distinct event types, sorted |

            Run the next cell first: it defines `WebhookEvent` and `SAMPLE_WEBHOOK_EVENTS`
            (deliberately not in time order).
            """
        ),
        code(
            '''
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
            print(f"{len(SAMPLE_WEBHOOK_EVENTS)=}")
            '''
        ),
        md("The stub:"),
        code(
            '''
            def summarize_webhooks(events: list[WebhookEvent]) -> dict[str, object]:
                """Summarize webhook events with sum, max and sorted."""
                raise NotImplementedError("Lab 1.9: implement summarize_webhooks()")
            '''
        ),
        md(
            "The check cell: note that `evt_1` and `evt_2` tie on the largest amount, and `evt_1` comes first in the list."
        ),
        code(
            """
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
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.9."""
    return [
        md(
            """
            ### Recap — Unit 1.9

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Iterable / iterator | `__iter__` gives an iterator; `__next__` gives items, then raises `StopIteration` | `[Symbol.iterator]`, `next()` → `{value, done}` |
            | `for` loop | `iter()` once, `next()` until `StopIteration` (`GET_ITER` / `FOR_ITER`) | `for...of` |
            | `iter(callable, sentinel)` | Call until the sentinel comes back: chunked reads | — |
            | `enumerate`, `zip(strict=True)` | Index + item; parallel iteration that checks lengths | `entries()`; no built-in zip |
            | `reversed`, `sorted`, `range` | Reverse iterator; new sorted list; lazy int sequence | `toReversed`, `toSorted` |
            | Comprehensions | `[expr for x in it if cond]`, dict and set forms; own scope; inlined since 3.12 | `map` + `filter` |
            | Nested `for` order | Left to right = outer to inner | nested `flatMap` |
            | Numeric built-ins | `round` ties to even; `sum(start=)`; `min`/`max` with `key` and `default` | `Math.*`, `reduce` |
            | `map` / `filter` | Lazy, single-use iterators; best with existing functions | eager array methods |
            | `any` / `all` | Short-circuit truth tests; `all([])` is `True` | `some` / `every` |
            | Conversion built-ins | `int`, `float`, `str`, `bytes`, `chr`, `ord`, `bin`/`hex`/`oct`, `format`, `repr`, `ascii` | `parseInt`, `String`, `toString(16)` |
            | Introspection | `type`, `isinstance`, `dir`, `vars`, `getattr`/`setattr`/`hasattr`/`delattr`, `help` | `typeof`, `instanceof`, `Reflect` |
            | `locals()` | A snapshot in functions since 3.13 (PEP 667) | — |
            | `eval` / `exec` / `compile` | Run arbitrary code; never on untrusted input | `eval`, `new Function` |
            | `ast.literal_eval` | Safe parsing of Python literals | `JSON.parse` |
            | Idioms | `enumerate`, `zip`, `in`, `any`/`all`, `dict.get`, EAFP | — |

            **Further reading**

            - [Built-in functions](https://docs.python.org/3/library/functions.html)
            - [Iterator types](https://docs.python.org/3/library/stdtypes.html#iterator-types),
              [glossary: iterable](https://docs.python.org/3/glossary.html#term-iterable),
              [glossary: EAFP](https://docs.python.org/3/glossary.html#term-EAFP)
            - [Tutorial: list comprehensions](https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions),
              [displays for lists, sets and dicts](https://docs.python.org/3/reference/expressions.html#displays-for-lists-sets-and-dictionaries)
            - [`ast.literal_eval`](https://docs.python.org/3/library/ast.html#ast.literal_eval),
              [`dis`](https://docs.python.org/3/library/dis.html)
            - [PEP 234 — Iterators](https://peps.python.org/pep-0234/),
              [PEP 202 — List comprehensions](https://peps.python.org/pep-0202/),
              [PEP 274 — Dict comprehensions](https://peps.python.org/pep-0274/)
            - [PEP 618 — Add optional length-checking to zip](https://peps.python.org/pep-0618/),
              [PEP 709 — Inlined comprehensions](https://peps.python.org/pep-0709/),
              [PEP 667 — Consistent views of namespaces](https://peps.python.org/pep-0667/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.9 and Lab 1.9."""
    return [
        *_overview_cells(),
        *_protocol_cells(),
        *_helper_cells(),
        *_comprehension_cells(),
        *_catalogue_cells(),
        *_map_filter_cells(),
        *_idiom_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
