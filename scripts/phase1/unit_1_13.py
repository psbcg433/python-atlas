"""Unit 1.13 — Iterators, Generators and itertools (with Lab 1.13)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import datetime as dt
import dis
import importlib.util
import inspect
import io
import itertools
import operator
import sys
import tracemalloc
from collections import Counter, deque  # noqa: F401 (deque: Lab 1.13)
from collections.abc import Callable, Generator, Iterable, Iterator
from pathlib import Path
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
            ## Unit 1.13 — Iterators, Generators and itertools

            **Objectives**

            - Tell an iterable (gives fresh iterators) from an iterator (single use), and write
              both as classes.
            - Write generator functions and expressions, and explain their lazy start, states,
              suspended frames and return values.
            - Build lazy, pull-based pipelines that process data of any size in constant memory.
            - Delegate with `yield from`, and drive two-way generators with `send`, `throw` and
              `close`.
            - See how `async def` coroutines grew out of generators, by driving one by hand.
            - Use every `itertools` building block, and know where the recipes live.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `[Symbol.iterator]()` | `__iter__()` | Called by `for`, `list()`, unpacking, `in`, … |
            | `iterator.next()` → `{value, done}` | `__next__()` returns the value, raises `StopIteration` | No result object; the end is an exception |
            | `function*` / `yield` | `def` containing `yield` | Any `yield` in the body makes it a generator function |
            | `yield*` | `yield from` | Also forwards `send` / `throw` and returns the sub-generator's return value |
            | `gen.next(value)` | `gen.send(value)` | The first call must send `None` (priming) |
            | `gen.return()` / `gen.throw(e)` | `gen.close()` / `gen.throw(e)` | `close` raises `GeneratorExit` inside the generator |
            | `async function` / `await` | `async def` / `await` | Coroutines are generator machinery underneath; you can drive one with `send` |
            | Iterator helpers (`.map`, `.take`, ES2025) | `itertools`, generator expressions | Python has had lazy tools since 2.3 |

            The next cell is this unit's setup (`scratch_dir` is the git-ignored folder used by
            file demos).
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _iterable_iterator_cells() -> list[NotebookNode]:
    """1.13.1 Iterable vs iterator."""
    return [
        md(
            """
            ### 1.13.1 Iterable vs iterator

            Unit 1.9.1 introduced the protocol; this section pins down the difference that causes
            real bugs.

            | | Iterable | Iterator |
            | --- | --- | --- |
            | Method | `__iter__()` returns an iterator | `__next__()` returns the next item or raises `StopIteration`; `__iter__()` returns `self` |
            | Examples | `list`, `tuple`, `str`, `dict`, `set`, `range` | file objects, generators, `map`, `filter`, `zip`, `enumerate`, `iter(list)` |
            | Loop it twice | works: each loop gets a **fresh** iterator | the second loop is **empty**: iterators are single use |

            Every iterator is also iterable (its `__iter__` returns itself), which is why you can
            loop over a `map` object, but only once.
            """
        ),
        code(
            """
            basket_prices = [249, 640, 162]
            print(f"{iter(basket_prices) is iter(basket_prices)=}  (fresh iterator each time)")

            with_gst = map(lambda price: round(price * 1.18), basket_prices)
            print(f"{iter(with_gst) is with_gst=}  (an iterator returns itself)")
            print(f"first pass:  {list(with_gst)}")
            print(f"second pass: {list(with_gst)}  (already consumed)")
            """
        ),
        md(
            """
            The `collections.abc` classes check the protocol: `Iterable` needs `__iter__`,
            `Iterator` needs both methods. The bug pattern below: a function loops over its
            argument twice. With a list it works; with a single-use iterator, the second loop
            silently sees nothing.
            """
        ),
        code(
            '''
            def price_report(prices: Iterable[int]) -> str:
                """Loops over prices twice: fine for iterables, wrong for iterators."""
                total = sum(prices)
                count = sum(1 for _ in prices)
                return f"total={total}, count={count}"


            print(f"{isinstance(basket_prices, Iterable)=}, {isinstance(basket_prices, Iterator)=}")
            print(f"{isinstance(iter(basket_prices), Iterator)=}")
            print(f"list:     {price_report(basket_prices)}")
            print(f"iterator: {price_report(iter(basket_prices))}  (count is wrong)")
            '''
        ),
        md(
            """
            > **Note:** when a function needs two passes, either accept a `Sequence` / `list`, or
            > call `list(prices)` once at the top. Guard against the bug with
            > `if iter(prices) is prices: prices = list(prices)`.

            **JS bridge: `Symbol.iterator`.** The protocols are the same idea with different
            spelling:

            ```javascript
            const prices = [249, 640];
            const it = prices[Symbol.iterator]();
            it.next();  // { value: 249, done: false }
            it.next();  // { value: 640, done: false }
            it.next();  // { value: undefined, done: true }
            ```

            Python's `next()` returns the value directly and signals the end with an exception,
            which `for` catches for you. `next(iterator, default)` returns `default` instead.
            """
        ),
        code(
            """
            price_iterator = iter([249, 640])
            print(next(price_iterator), next(price_iterator))
            print(f"{next(price_iterator, 'done')=}")
            print(f"next() after the end: {raised_error_name(lambda: next(price_iterator))}")
            """
        ),
    ]


def _custom_iterator_cells() -> list[NotebookNode]:
    """1.13.2 Custom iterator classes."""
    return [
        md(
            """
            ### 1.13.2 Custom iterator classes

            **Separate the iterable from its iterator.** The container (`DeliveryWindow`) stores
            the data and returns a **new** iterator object from `__iter__`; the iterator
            (`DeliveryWindowIterator`) holds the position. Then any number of loops, even nested
            ones, work independently.
            """
        ),
        code(
            '''
            class DeliveryWindowIterator:
                """Iterator over the days of a DeliveryWindow; holds the position."""

                def __init__(self, first_day: dt.date, day_count: int) -> None:
                    self.next_day = first_day
                    self.days_left = day_count

                def __iter__(self) -> DeliveryWindowIterator:
                    return self

                def __next__(self) -> dt.date:
                    if self.days_left == 0:
                        raise StopIteration
                    current_day = self.next_day
                    self.next_day += dt.timedelta(days=1)
                    self.days_left -= 1
                    return current_day


            class DeliveryWindow:
                """Iterable: a range of delivery dates; every loop gets a new iterator."""

                def __init__(self, first_day: dt.date, day_count: int) -> None:
                    self.first_day = first_day
                    self.day_count = day_count

                def __iter__(self) -> DeliveryWindowIterator:
                    return DeliveryWindowIterator(self.first_day, self.day_count)
            '''
        ),
        md(
            """
            The nested loop pairs every day with every day (3 × 3 = 9 pairs) because the inner
            and outer loops each got their own iterator.
            """
        ),
        code(
            """
            festival_window = DeliveryWindow(dt.date(2026, 11, 7), 3)
            print([day.isoformat() for day in festival_window])
            print([day.isoformat() for day in festival_window])  # works again
            pairs = [(first.day, second.day) for first in festival_window for second in festival_window]
            print(f"{len(pairs)=}")
            """
        ),
        md(
            """
            **The shortcut that breaks.** Making the container its own iterator (`__iter__`
            returns `self`) looks simpler, but the position lives on the container. The nested
            loop shares one position: the inner loop consumes days 2 and 3 during the outer
            loop's first pass, so it produces 2 pairs instead of 9, and a later loop is empty.
            """
        ),
        code(
            '''
            class OneShotWindow:
                """Bug: the container is its own iterator."""

                def __init__(self, first_day: dt.date, day_count: int) -> None:
                    self.next_day = first_day
                    self.days_left = day_count

                def __iter__(self) -> OneShotWindow:
                    return self

                def __next__(self) -> dt.date:
                    if self.days_left == 0:
                        raise StopIteration
                    self.days_left -= 1
                    self.next_day += dt.timedelta(days=1)
                    return self.next_day - dt.timedelta(days=1)


            one_shot = OneShotWindow(dt.date(2026, 11, 7), 3)
            nested_pairs = [(first.day, second.day) for first in one_shot for second in one_shot]
            print(f"{len(nested_pairs)=}, {list(one_shot)=}")
            '''
        ),
        md(
            """
            **The `__getitem__` sequence fallback.** Before the iterator protocol existed (2.2),
            `for` worked on anything with `__getitem__`: Python calls it with 0, 1, 2, … until it
            raises `IndexError`. `iter()` still supports that, wrapping the object in a generic
            `iterator`. The catch: `isinstance(obj, Iterable)` is **False**, because the ABC only
            checks for `__iter__`. The reliable test is to call `iter(obj)`.
            """
        ),
        code(
            '''
            class SeatRow:
                """Old-style sequence: only __getitem__, no __iter__."""

                def __init__(self, seat_count: int) -> None:
                    self.seat_count = seat_count

                def __getitem__(self, index: int) -> str:
                    if index >= self.seat_count:
                        raise IndexError(index)
                    return f"A{index + 1}"


            front_row = SeatRow(4)
            print(f"{list(front_row)=}, {'A3' in front_row=}")
            print(f"{type(iter(front_row)).__name__=}")
            print(f"{isinstance(front_row, Iterable)=}  (the ABC misses the fallback)")
            '''
        ),
    ]


def _generator_function_cells() -> list[NotebookNode]:
    """1.13.3 Generator functions."""
    return [
        md(
            """
            ### 1.13.3 Generator functions

            Writing iterator classes by hand is tedious. A **generator function**, a `def` that
            contains `yield`, does it for you. Calling it does **not** run the body: it returns a
            generator object (an iterator). Each `next()` runs the body until the next `yield`,
            hands out the yielded value, and **suspends** the function with all its local
            variables intact. When the body ends, `StopIteration` is raised.
            """
        ),
        code(
            '''
            def order_statuses() -> Iterator[str]:
                """Yield the stages of an order, printing as the body runs."""
                print("  body starts")
                yield "placed"
                print("  resumed after 'placed'")
                yield "packed"
                print("  resumed after 'packed'")
                yield "shipped"
                print("  body ends")


            status_generator = order_statuses()
            print(f"{type(status_generator).__name__=}  (nothing printed yet: lazy start)")
            print(f"{next(status_generator)=}")
            print(f"{next(status_generator)=}")
            print(f"rest: {list(status_generator)}")
            '''
        ),
        md(
            """
            **States.** `inspect.getgeneratorstate(gen)` reports one of four states. `GEN_RUNNING`
            can only be observed from inside the generator itself, so the next cell's generator
            inspects itself through a global name.

            | State | Meaning |
            | --- | --- |
            | `GEN_CREATED` | created, body not started |
            | `GEN_RUNNING` | currently executing |
            | `GEN_SUSPENDED` | paused at a `yield` |
            | `GEN_CLOSED` | finished (returned, raised, or closed) |
            """
        ),
        code(
            '''
            def self_reporting() -> Iterator[str]:
                """Yield its own state while running."""
                yield inspect.getgeneratorstate(watched_generator)


            watched_generator = self_reporting()
            states = [inspect.getgeneratorstate(watched_generator)]
            states.append(next(watched_generator))
            states.append(inspect.getgeneratorstate(watched_generator))
            states.append(raised_error_name(lambda: next(watched_generator)))
            states.append(inspect.getgeneratorstate(watched_generator))
            print(states)
            '''
        ),
        md(
            """
            #### Under the hood: suspended frames

            A generator owns its frame (`gi_frame`). While suspended, the frame keeps the current
            line and all locals; that is what "pausing" means. `gi_suspended` (*New in 3.11*)
            says whether it is paused at a `yield`. When the generator finishes, the frame is
            released and `gi_frame` becomes `None`.
            """
        ),
        code(
            '''
            def running_totals(amounts: list[int]) -> Iterator[int]:
                """Yield the running total after each amount."""
                total = 0
                for amount in amounts:
                    total += amount
                    yield total


            totals = running_totals([249, 640, 162])
            next(totals)
            next(totals)
            frame = totals.gi_frame
            print(f"{totals.gi_suspended=}, {frame.f_locals['total']=}, {frame.f_locals['amount']=}")
            print(f"{frame.f_lineno - totals.gi_code.co_firstlineno=} (line offset of the yield)")
            print(f"{list(totals)=}, {totals.gi_frame=}")
            '''
        ),
        md(
            """
            The compiler marks generator functions with the `CO_GENERATOR` flag. Their bytecode
            starts with `RETURN_GENERATOR` (which builds the generator object instead of running
            the body) and pauses at `YIELD_VALUE`. Opcode names vary between versions.
            """
        ),
        code(
            """
            print(f"{bool(running_totals.__code__.co_flags & inspect.CO_GENERATOR)=}")
            print(f"{inspect.isgeneratorfunction(running_totals)=}, {inspect.isgenerator(totals)=}")
            opnames = [instruction.opname for instruction in dis.get_instructions(running_totals)]
            print(f"{opnames[0]=}, {'YIELD_VALUE' in opnames=}")
            """
        ),
        md(
            """
            **`return` in a generator.** A `return value` statement ends the generator; the
            value travels as `StopIteration.value`. A `for` loop discards it, but code that calls
            `next()` itself (and `yield from`, 1.13.6) can read it.
            """
        ),
        code(
            '''
            def take_until_budget(prices: list[int], budget: int) -> Generator[int, None, int]:
                """Yield prices while they fit the budget; return the money left."""
                for price in prices:
                    if price > budget:
                        break
                    budget -= price
                    yield price
                return budget


            shopper = take_until_budget([249, 640, 162], budget=1000)
            bought = [next(shopper), next(shopper)]
            try:
                next(shopper)
            except StopIteration as stop:
                print(f"{bought=}, money left: {stop.value}")
            '''
        ),
        md(
            """
            > **Note:** the type hint `Generator[YieldType, SendType, ReturnType]` describes all
            > three channels. `Iterator[int]` is enough when only `yield` is used. `SendType` and
            > `ReturnType` default to `None` (*New in 3.13*, PEP 696), so `Generator[str, int]`
            > means "yields `str`, receives `int`, returns nothing".
            """
        ),
    ]


def _generator_expression_cells() -> list[NotebookNode]:
    """1.13.4 Generator expressions."""
    return [
        md(
            """
            ### 1.13.4 Generator expressions

            A **generator expression** is a comprehension in parentheses: `(expr for x in
            iterable if condition)`. It builds a generator, not a list. When it is the only
            argument of a call, the extra parentheses can be dropped:
            `sum(price * 2 for price in prices)`.
            """
        ),
        code(
            """
            basket_prices = [249, 640, 162, 980]
            doubled_lazily = (price * 2 for price in basket_prices if price < 900)
            print(f"{type(doubled_lazily).__name__=}")
            print(f"{sum(price * 2 for price in basket_prices)=}")
            print(f"{max(len(sku) for sku in ['TEA-500G', 'RICE-5KG', 'SOAP'])=}")
            """
        ),
        *predict_cells(
            snippet="""
            expensive = (price for price in [249, 640, 980] if price > 500)
            print(list(expensive))
            print(list(expensive))
            print(980 in expensive)
            """,
            answer="""
            `[640, 980]`, then `[]`, then `False`. A generator expression is an iterator: the
            first `list()` consumes it, so the second sees nothing, and `in` searches what is left
            (nothing).
            """,
            proof="""
            expensive = (price for price in [249, 640, 980] if price > 500)
            print(list(expensive))
            print(list(expensive))
            print(980 in expensive)
            """,
        ),
        md(
            """
            One subtle rule: the **first** `in` iterable is evaluated immediately, when the
            expression is created; everything else is lazy. So a bad name in the first `for`
            fails at once, while an error in the expression part waits until the item is pulled.
            """
        ),
        code(
            """
            print(f"bad first iterable: {raised_error_name(lambda: (x for x in missing_prices))}")  # noqa: F821
            lazy_division = (1000 // quantity for quantity in [4, 0, 2])
            print(f"created fine; first item: {next(lazy_division)}")
            print(f"second item: {raised_error_name(lambda: next(lazy_division))}")
            """
        ),
        md(
            """
            **Memory.** A list comprehension materializes every element; a generator expression
            holds only its frame, whatever the input size. `sys.getsizeof` shows the containers;
            `tracemalloc` shows the **peak** memory of summing a million squares each way
            (including the int objects themselves). Exact numbers vary by version.
            """
        ),
        code(
            '''
            def peak_bytes(thunk: Callable[[], object]) -> int:
                """Return the peak traced memory while running thunk."""
                tracemalloc.start()
                try:
                    thunk()
                    return tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()


            squares_list = [number * number for number in range(1_000_000)]
            squares_generator = (number * number for number in range(1_000_000))
            print(f"list object: {sys.getsizeof(squares_list):,} bytes")
            print(f"generator object: {sys.getsizeof(squares_generator)} bytes")
            del squares_list
            list_peak = peak_bytes(lambda: sum([number * number for number in range(1_000_000)]))
            generator_peak = peak_bytes(lambda: sum(number * number for number in range(1_000_000)))
            print(f"peak with list: {list_peak / 1e6:.1f} MB, with generator: {generator_peak / 1e3:.1f} kB")
            '''
        ),
        md(
            """
            | Use | When |
            | --- | --- |
            | List comprehension | you need the results more than once, `len()`, indexing, or sorting |
            | Generator expression | you consume the results once (`sum`, `max`, `any`, `join`, a loop), or the input is large or infinite |
            """
        ),
    ]


def _pipeline_cells() -> list[NotebookNode]:
    """1.13.5 Lazy pipelines."""
    return [
        md(
            """
            ### 1.13.5 Lazy pipelines

            Chain generators so that each stage consumes the previous one: **read → parse →
            filter → aggregate**. Nothing happens until the last stage asks for a value; then the
            request travels up the chain, and **one item at a time** flows down. Memory stays
            constant whatever the input size, and work stops as soon as the consumer stops.

            ```mermaid
            flowchart RL
                aggregate["sum()<br/>aggregate"] -- "next()" --> filter_stage["only_city()<br/>filter"]
                filter_stage -- "next()" --> parse_stage["parse_sales()<br/>parse"]
                parse_stage -- "next()" --> read_stage["read_lines()<br/>read"]
                read_stage -. "one line" .-> parse_stage
                parse_stage -. "one Sale" .-> filter_stage
                filter_stage -. "one matching Sale" .-> aggregate
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            pull:   sum() --next()--> only_city() --next()--> parse_sales() --next()--> read_lines()
            push:   sum() <--Sale---- only_city() <--Sale---- parse_sales() <--line---- read_lines()
            (one item travels the whole chain before the next line is read)
            ```

            </details>

            The stages below print as they work, so the trace shows the interleaving.
            """
        ),
        code(
            '''
            class Sale(NamedTuple):
                city: str
                sku: str
                amount: int


            def read_lines(stream: io.TextIOBase) -> Iterator[str]:
                """Stage 1: yield non-empty lines."""
                for line in stream:
                    if line.strip():
                        print(f"    read  {line.strip()!r}")
                        yield line


            def parse_sales(lines: Iterable[str]) -> Iterator[Sale]:
                """Stage 2: turn 'city,sku,amount' lines into Sale records."""
                for line in lines:
                    city, sku, amount = line.strip().split(",")
                    yield Sale(city, sku, int(amount))


            def only_city(sales: Iterable[Sale], city: str) -> Iterator[Sale]:
                """Stage 3: keep one city's sales."""
                for sale in sales:
                    if sale.city == city:
                        print(f"    keep  {sale.sku} {sale.amount}")
                        yield sale
            '''
        ),
        md(
            """
            Stage 4 is `sum`. Building the pipeline prints nothing; `sum` then pulls each line
            through every stage before the next line is read.
            """
        ),
        code(
            """
            sales_csv = "Pune,TEA-500G,249\\nDelhi,RICE-5KG,640\\n\\nPune,SOAP-3PK,162\\nGoa,TEA-500G,249\\n"
            pune_sales = only_city(parse_sales(read_lines(io.StringIO(sales_csv))), "Pune")
            print("pipeline built, nothing read yet")
            pune_total = sum(sale.amount for sale in pune_sales)
            print(f"{pune_total=}")
            """
        ),
        md(
            """
            **Early termination.** Asking only for the first Pune sale reads **one** line; the
            rest of the input is never touched. With a 10 GB file that is the difference between
            milliseconds and minutes.
            """
        ),
        code(
            """
            first_pune_sale = next(only_city(parse_sales(read_lines(io.StringIO(sales_csv))), "Pune"))
            print(f"{first_pune_sale=}")
            """
        ),
    ]


def _yield_from_cells() -> list[NotebookNode]:
    """1.13.6 yield from."""
    return [
        md(
            """
            ### 1.13.6 `yield from`

            `yield from sub_iterable` hands control to another iterable until it is exhausted:
            every item it produces is yielded to our caller. For plain iteration it is the same as
            `for item in sub_iterable: yield item`, just shorter. (It does more for two-way
            generators, 1.13.7.)
            """
        ),
        code(
            '''
            def warehouse_skus() -> Iterator[str]:
                yield from ["TEA-500G", "RICE-5KG"]


            def store_skus() -> Iterator[str]:
                yield from ("SOAP-3PK", "TEA-500G")


            def all_skus() -> Iterator[str]:
                """Delegate to two sub-generators in turn."""
                yield from warehouse_skus()
                yield from store_skus()


            print(list(all_skus()))
            '''
        ),
        md(
            """
            **Recursive tree walks.** A recursive generator yields its own items and delegates
            the subtrees with `yield from`. The category tree below is nested dicts; the walk
            yields every path, depth first.
            """
        ),
        code(
            '''
            category_tree: dict[str, dict[str, Any]] = {
                "Grocery": {"Tea": {}, "Rice": {"Basmati": {}, "Sona Masoori": {}}},
                "Home": {"Cleaning": {"Soap": {}}},
            }


            def category_paths(tree: dict[str, Any], prefix: str = "") -> Iterator[str]:
                """Yield 'A/B/C' paths for every node of a nested-dict tree."""
                for name, subtree in tree.items():
                    path = f"{prefix}/{name}" if prefix else name
                    yield path
                    yield from category_paths(subtree, path)


            for path in category_paths(category_tree):
                print(f"  {path}")
            '''
        ),
        md(
            """
            **Capturing return values.** `result = yield from sub_generator()` evaluates to the
            sub-generator's `return` value (its `StopIteration.value`). This lets a sub-generator
            produce items **and** report a summary. Below, each section of an inventory file
            yields its items and returns how many it had.
            """
        ),
        code(
            '''
            def section_items(section_name: str, items: list[str]) -> Generator[str, None, int]:
                """Yield 'section: item' strings; return the item count."""
                for item in items:
                    yield f"{section_name}: {item}"
                return len(items)


            def inventory(sections: dict[str, list[str]]) -> Generator[str, None, dict[str, int]]:
                """Yield every item; return the count per section."""
                counts = {}
                for section_name, items in sections.items():
                    counts[section_name] = yield from section_items(section_name, items)
                return counts


            inventory_walk = inventory({"Shelf A": ["tea", "rice"], "Shelf B": ["soap"]})
            print(list(itertools.islice(inventory_walk, 10)))
            print(f"{inspect.getgeneratorstate(inventory_walk)=}")


            def collect_return(generator: Generator[Any, None, Any]) -> Any:
                """Exhaust a generator and return its return value."""
                while True:
                    try:
                        next(generator)
                    except StopIteration as stop:
                        return stop.value


            print(f"{collect_return(inventory({'Shelf A': ['tea', 'rice'], 'Shelf B': ['soap']}))=}")
            '''
        ),
    ]


def _two_way_cells() -> list[NotebookNode]:
    """1.13.7 Two-way generators."""
    return [
        md(
            """
            ### 1.13.7 Two-way generators

            `yield` is also an **expression**: `received = yield value` hands out `value`, and
            when the generator is resumed with `gen.send(something)`, `received` becomes
            `something`. `next(gen)` is the same as `gen.send(None)`.

            | Method | Effect at the paused `yield` |
            | --- | --- |
            | `gen.send(value)` | `yield` evaluates to `value`; runs to the next `yield`, returns its value |
            | `gen.throw(exception)` | the exception is raised at the `yield` |
            | `gen.close()` | `GeneratorExit` is raised at the `yield`; the generator must finish |

            **Priming.** A new generator has not reached a `yield` yet, so there is nothing to
            receive a value: the first call must be `next(gen)` or `gen.send(None)`.
            """
        ),
        code(
            '''
            def duplicate_detector() -> Generator[bool | None, str]:
                """Receive order ids; answer True if the id was seen before."""
                seen_ids: set[str] = set()
                answer: bool | None = None
                while True:
                    order_id = yield answer
                    answer = order_id in seen_ids
                    seen_ids.add(order_id)


            detector = duplicate_detector()
            print(f"priming: {next(detector)=}")
            print([detector.send(order_id) for order_id in ["A-1", "A-2", "A-1", "A-3", "A-2"]])
            unprimed = duplicate_detector()
            try:
                unprimed.send("A-1")
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            '''
        ),
        md(
            """
            Forgetting to prime is so common that coroutine-style generators were often wrapped
            in a small decorator (Unit 1.12) that calls `next()` once.
            """
        ),
        code(
            '''
            def primed[**P](
                generator_function: Callable[P, Generator[Any, Any, Any]],
            ) -> Callable[P, Generator[Any, Any, Any]]:
                """Decorator: create the generator and advance it to the first yield."""

                def start(*args: P.args, **kwargs: P.kwargs) -> Generator[Any, Any, Any]:
                    generator = generator_function(*args, **kwargs)
                    next(generator)
                    return generator

                return start


            ready_detector = primed(duplicate_detector)()
            print([ready_detector.send(order_id) for order_id in ["B-7", "B-7"]])
            '''
        ),
        md(
            """
            **`throw`** raises an exception at the paused `yield`. The generator may handle it
            and continue (its next `yield` value is what `throw` returns), or let it propagate to
            the caller.
            """
        ),
        code(
            '''
            def resilient_reader(lines: list[str]) -> Iterator[str]:
                """Yield lines; on a ValueError from the caller, report and carry on."""
                for line in lines:
                    try:
                        yield line
                    except ValueError as error:
                        yield f"skipped after error: {error}"


            reader = resilient_reader(["line 1", "line 2", "line 3"])
            print(next(reader))
            print(reader.throw(ValueError("bad checksum")))
            print(next(reader), next(reader))
            '''
        ),
        md(
            """
            **`close` and cleanup.** `close()` raises `GeneratorExit` (a `BaseException`) at the
            paused `yield`. Put cleanup in a `finally` block: it runs whether the generator
            finishes, fails, is closed explicitly, or is garbage-collected half-way. A generator
            that **yields** in response to `GeneratorExit` is a bug, reported as `RuntimeError`.
            """
        ),
        code(
            '''
            def database_rows(table: str) -> Iterator[str]:
                """Pretend to stream rows from a connection; always release it."""
                print(f"  open connection for {table}")
                try:
                    for row_number in itertools.count(1):
                        yield f"{table} row {row_number}"
                finally:
                    print(f"  close connection for {table}")


            rows = database_rows("orders")
            print(next(rows), "|", next(rows))
            rows.close()
            print(f"{inspect.getgeneratorstate(rows)=}, {issubclass(GeneratorExit, Exception)=}")
            for row in database_rows("customers"):  # noqa: B007
                break  # leaving the loop drops the generator; finally runs when it is collected
            '''
        ),
        md("The `RuntimeError` case, for completeness:"),
        code(
            '''
            def refuses_to_stop() -> Iterator[int]:
                """Bug: yields again after GeneratorExit."""
                try:
                    yield 1
                except GeneratorExit:
                    yield 2


            stubborn = refuses_to_stop()
            next(stubborn)
            try:
                stubborn.close()
            except RuntimeError as error:
                print(f"{type(error).__name__}: {error}")
            '''
        ),
    ]


def _async_bridge_cells() -> list[NotebookNode]:
    """1.13.8 From generators to async."""
    return [
        md(
            """
            ### 1.13.8 From generators to async

            `async` / `await` did not appear from nowhere: each step below added one capability
            to generators, and the last one gave coroutines their own syntax.

            | PEP | Python | Added | Why it mattered |
            | --- | --- | --- | --- |
            | [255](https://peps.python.org/pep-0255/) | 2.2 | `yield`: simple generators | functions that pause and resume |
            | [342](https://peps.python.org/pep-0342/) | 2.5 | `send`, `throw`, `close`; `yield` as an expression | generators become **coroutines**: a scheduler can resume them with results |
            | [380](https://peps.python.org/pep-0380/) | 3.3 | `yield from` | a coroutine can call another and get its return value (asyncio 3.4 was built on this) |
            | [492](https://peps.python.org/pep-0492/) | 3.5 | `async def`, `await`, `__await__` | native coroutines, a distinct type that cannot be confused with a generator |
            | [525](https://peps.python.org/pep-0525/) | 3.6 | async generators | `yield` inside `async def` |

            A coroutine is driven exactly like a two-way generator: `coroutine.send(value)` runs
            it to the next point where something deep inside an `await` **yields**, and
            `StopIteration.value` carries its result. The event loop (Phase 5) is "just" the code
            that calls `send` and decides when.

            The next cell defines an awaitable, `Delay`, whose `__await__` is a generator that
            yields a request to whoever drives the coroutine, and receives a reply.
            """
        ),
        code(
            '''
            class Delay:
                """Awaitable: ask the driver to wait, receive its reply."""

                def __init__(self, seconds: float) -> None:
                    self.seconds = seconds

                def __await__(self) -> Generator[tuple[str, float], str, str]:
                    reply = yield ("sleep", self.seconds)  # goes out through coroutine.send()
                    return reply


            async def fetch_order(order_id: int) -> dict[str, Any]:
                """A native coroutine that awaits twice."""
                first_reply = await Delay(0.5)
                second_reply = await Delay(0.2)
                return {"order_id": order_id, "replies": [first_reply, second_reply]}
            '''
        ),
        md(
            """
            Drive it by hand. Calling `fetch_order(42)` creates a coroutine object without running
            it (like a generator); each `send` runs it to the next yielded request.
            """
        ),
        code(
            """
            order_coroutine = fetch_order(42)
            print(f"{inspect.getcoroutinestate(order_coroutine)=}")
            first_request = order_coroutine.send(None)
            print(f"{first_request=}, {inspect.getcoroutinestate(order_coroutine)=}")
            second_request = order_coroutine.send("woke after 0.5 s")
            print(f"{second_request=}")
            try:
                order_coroutine.send("woke after 0.2 s")
            except StopIteration as stop:
                print(f"result: {stop.value}")
            """
        ),
        md(
            """
            A **minimal event loop** is a loop around `send`. This one runs several coroutines on
            a virtual clock: it always resumes the coroutine whose wake-up time is earliest, so
            the two orders interleave and both finish at t=0.7 s instead of 1.4 s: they waited
            concurrently. Real asyncio does the same with sockets and timers (Phase 5).
            """
        ),
        code(
            '''
            def run_all(coroutines: list[Any]) -> list[Any]:
                """Run coroutines that await Delay, interleaving them on a virtual clock."""
                ready = [(0.0, index, coroutine, None) for index, coroutine in enumerate(coroutines)]
                results: list[Any] = [None] * len(coroutines)
                while ready:
                    ready.sort(key=lambda entry: entry[0])
                    now, index, coroutine, reply = ready.pop(0)
                    try:
                        _, seconds = coroutine.send(reply)
                    except StopIteration as stop:
                        results[index] = stop.value
                        print(f"  t={now:.1f}s order {stop.value['order_id']} done")
                        continue
                    ready.append((now + seconds, index, coroutine, f"woke at {now + seconds:.1f}s"))
                return results


            finished = run_all([fetch_order(1), fetch_order(2)])
            print(finished[1])
            '''
        ),
    ]


def _itertools_cells() -> list[NotebookNode]:
    """1.13.9 The itertools module (reference table, one demo per row)."""
    return [
        md(
            """
            ### 1.13.9 The `itertools` module

            `itertools` provides fast, memory-efficient building blocks that return **iterators**.
            Every row of the table has its own demo below, grouped as in the table. Infinite
            iterators are always capped with `islice`, `zip` or `takewhile`.

            | Group | Function | Yields | Example → result |
            | --- | --- | --- | --- |
            | Infinite | `count(start=0, step=1)` | start, start+step, … | `count(100, 5)` → 100 105 110 … |
            | Infinite | `cycle(iterable)` | the items, repeated forever | `cycle("AB")` → A B A B … |
            | Infinite | `repeat(obj, times=None)` | `obj`, `times` times (or forever) | `repeat(0, 3)` → 0 0 0 |
            | Terminating | `accumulate(iterable, func=add, *, initial=None)` | running results | `accumulate([1, 2, 3])` → 1 3 6 |
            | Terminating | `batched(iterable, n, *, strict=False)` | tuples of `n` items | `batched("ABCDE", 2)` → AB CD E |
            | Terminating | `chain(*iterables)` | items of each iterable in turn | `chain("AB", "CD")` → A B C D |
            | Terminating | `chain.from_iterable(iterable)` | same, from one iterable of iterables | `chain.from_iterable(["AB", "CD"])` → A B C D |
            | Terminating | `compress(data, selectors)` | data items whose selector is true | `compress("ABC", [1, 0, 1])` → A C |
            | Terminating | `dropwhile(predicate, iterable)` | everything after the predicate first fails | `dropwhile(lambda x: x < 3, [1, 4, 1])` → 4 1 |
            | Terminating | `takewhile(predicate, iterable)` | items until the predicate first fails | `takewhile(lambda x: x < 3, [1, 4, 1])` → 1 |
            | Terminating | `filterfalse(predicate, iterable)` | items where the predicate is false | `filterfalse(str.isdigit, "a1b")` → a b |
            | Terminating | `groupby(iterable, key=None)` | `(key, group)` for each run of equal keys | `groupby("AAB")` → (A, AA) (B, B) |
            | Terminating | `islice(iterable, stop)` / `(start, stop, step)` | a slice of any iterator | `islice("ABCDEF", 1, 5, 2)` → B D |
            | Terminating | `pairwise(iterable)` | overlapping pairs | `pairwise("ABC")` → AB BC |
            | Terminating | `starmap(function, iterable)` | `function(*args)` for each args tuple | `starmap(pow, [(2, 3)])` → 8 |
            | Terminating | `tee(iterable, n=2)` | `n` independent iterators | `tee("AB")` → two iterators |
            | Terminating | `zip_longest(*iterables, fillvalue=None)` | zip to the **longest** input | `zip_longest("AB", "x", fillvalue="-")` → Ax B- |
            | Combinatoric | `product(*iterables, repeat=1)` | Cartesian product | `product("AB", "12")` → A1 A2 B1 B2 |
            | Combinatoric | `permutations(iterable, r=None)` | ordered arrangements | `permutations("ABC", 2)` → AB AC BA … (6) |
            | Combinatoric | `combinations(iterable, r)` | unordered selections, no repeats | `combinations("ABC", 2)` → AB AC BC |
            | Combinatoric | `combinations_with_replacement(iterable, r)` | unordered selections, repeats allowed | `…("AB", 2)` → AA AB BB |

            #### Infinite iterators

            **`count(start, step)`**: an endless counter, often zipped with finite data to number
            it, or used for generated ids.
            """
        ),
        code(
            """
            invoice_numbers = itertools.count(1001)
            print([f"INV-{next(invoice_numbers)}" for _ in range(3)])
            print(list(zip(["tea", "rice", "soap"], itertools.count(10, 10), strict=False)))
            """
        ),
        md(
            "**`cycle(iterable)`**: repeat the items forever (round-robin assignment, alternating styles)."
        ),
        code(
            """
            delivery_agents = itertools.cycle(["Asha", "Ravi"])
            orders = ["A-1", "A-2", "A-3", "A-4", "A-5"]
            print([(order, next(delivery_agents)) for order in orders])
            """
        ),
        md(
            "**`repeat(obj, times)`**: the same object again and again; handy as a constant argument to `map`."
        ),
        code(
            """
            print(list(itertools.repeat("-", 5)))
            print(list(map(pow, [2, 3, 4], itertools.repeat(2))))  # noqa: B912 (repeat is infinite)
            """
        ),
        md(
            """
            #### Terminating iterators

            **`accumulate(iterable, func, initial=None)`**: running totals by default; any
            two-argument function works (`max` gives a running maximum).
            """
        ),
        code(
            """
            daily_sales = [450, 1200, 300, 1500]
            print(f"{list(itertools.accumulate(daily_sales))=}")
            print(f"{list(itertools.accumulate(daily_sales, max))=}")
            print(f"{list(itertools.accumulate(daily_sales, operator.add, initial=5000))=}")
            """
        ),
        md(
            """
            **`batched(iterable, n)`** (*New in 3.12*): chunks of `n` items; the last may be
            shorter. `strict=True` (*New in 3.13*) raises `ValueError` for a short last batch.
            """
        ),
        code(
            """
            order_ids = ["A-1", "A-2", "A-3", "A-4", "A-5"]
            print(list(itertools.batched(order_ids, 2, strict=False)))
            if sys.version_info >= (3, 13):
                print(
                    f"strict: {raised_error_name(lambda: list(itertools.batched(order_ids, 2, strict=True)))}"
                )
            else:
                print("batched(strict=True) needs Python 3.13; skipped")
            """
        ),
        md("**`chain(*iterables)`**: one iterator over several iterables, without copying them."),
        code(
            """
            morning_orders, evening_orders = ["A-1", "A-2"], ("B-1",)
            print(list(itertools.chain(morning_orders, evening_orders, "C")))
            """
        ),
        md(
            """
            **`chain.from_iterable(iterable)`**: the same when the iterables arrive as one
            (possibly lazy) iterable. It flattens exactly **one** level.
            """
        ),
        code(
            """
            orders_per_store = {"Pune": ["A-1", "A-2"], "Goa": ["B-1"]}
            print(list(itertools.chain.from_iterable(orders_per_store.values())))
            """
        ),
        md(
            "**`compress(data, selectors)`**: keep the items whose selector is truthy (a boolean mask)."
        ),
        code(
            """
            skus = ["TEA-500G", "RICE-5KG", "SOAP-3PK"]
            in_stock = [True, False, True]
            print(list(itertools.compress(skus, in_stock)))
            """
        ),
        md(
            "**`dropwhile(predicate, iterable)`**: skip items while the predicate holds, then yield everything (it never checks again)."
        ),
        code(
            """
            log_lines = ["# header", "# generated 2026-11-05", "INFO start", "# inline comment", "ERROR stop"]
            print(list(itertools.dropwhile(lambda line: line.startswith("#"), log_lines)))
            """
        ),
        md(
            "**`takewhile(predicate, iterable)`**: yield items while the predicate holds, then stop (safe on infinite input)."
        ),
        code(
            """
            sorted_prices = [99, 149, 249, 640, 980]
            print(list(itertools.takewhile(lambda price: price < 300, sorted_prices)))
            print(list(itertools.takewhile(lambda n: n * n < 50, itertools.count(1))))
            """
        ),
        md("**`filterfalse(predicate, iterable)`**: the complement of `filter`."),
        code(
            """
            quantities = ["3", "two", "10", "x"]
            print(f"{list(filter(str.isdigit, quantities))=}")
            print(f"{list(itertools.filterfalse(str.isdigit, quantities))=}")
            """
        ),
        md(
            """
            **`groupby(iterable, key)`**: groups **consecutive** items with the same key, like
            Unix `uniq`, not SQL `GROUP BY`. Sort by the same key first to get one group per key.
            Each group is an iterator that is invalidated when you advance to the next group, so
            consume it immediately.
            """
        ),
        code(
            """
            sales = [("Pune", 249), ("Pune", 162), ("Goa", 640), ("Pune", 80)]
            unsorted_groups = [
                (city, len(list(group))) for city, group in itertools.groupby(sales, key=operator.itemgetter(0))
            ]
            print(f"{unsorted_groups=}  (runs, not totals)")
            by_city = sorted(sales, key=operator.itemgetter(0))
            print(
                {
                    city: sum(amount for _, amount in group)
                    for city, group in itertools.groupby(by_city, key=operator.itemgetter(0))
                }
            )
            """
        ),
        md(
            """
            **`islice(iterable, stop)` / `islice(iterable, start, stop, step)`**: slicing for any
            iterator (no negative indices). It consumes the skipped items.
            """
        ),
        code(
            """
            print(list(itertools.islice(itertools.count(1), 5)))
            print(list(itertools.islice("ABCDEFGH", 2, 7, 2)))
            report_lines = iter(["header", "row 1", "row 2", "row 3"])
            print(f"{list(itertools.islice(report_lines, 1, None))=}  (skip a header)")
            """
        ),
        md(
            "**`pairwise(iterable)`** (*New in 3.10*): consecutive overlapping pairs, e.g. for differences."
        ),
        code(
            """
            stock_levels = [120, 95, 95, 40]
            print(list(itertools.pairwise(stock_levels)))
            print(f"changes: {[later - earlier for earlier, later in itertools.pairwise(stock_levels)]}")
            """
        ),
        md(
            "**`starmap(function, iterable)`**: like `map`, but each item is unpacked into the arguments."
        ),
        code(
            """
            line_items = [(249, 2), (640, 1), (162, 3)]
            print(list(itertools.starmap(operator.mul, line_items)))
            """
        ),
        md(
            """
            **`tee(iterable, n)`**: split one iterator into `n` independent ones. It buffers the
            items one copy has seen and another has not, so if one runs far ahead, memory grows.
            Do not use the original iterator after calling `tee`.
            """
        ),
        code(
            """
            price_feed = iter([249, 640, 162])
            for_total, for_maximum = itertools.tee(price_feed)
            print(f"{sum(for_total)=}, {max(for_maximum)=}")
            """
        ),
        md(
            "**`zip_longest(*iterables, fillvalue)`**: like `zip`, but runs to the longest input, padding the gaps."
        ),
        code(
            """
            skus = ["TEA-500G", "RICE-5KG", "SOAP-3PK"]
            stock_counts = [40, 12]
            print(list(itertools.zip_longest(skus, stock_counts, fillvalue=0)))
            """
        ),
        md(
            """
            #### Combinatoric iterators

            **`product(*iterables, repeat=1)`**: the Cartesian product, the same as nested `for`
            loops.
            """
        ),
        code(
            """
            sizes, colours = ["S", "M"], ["red", "blue"]
            print([f"{size}-{colour}" for size, colour in itertools.product(sizes, colours)])
            print(f"{len(list(itertools.product('01', repeat=4)))=}  (4-bit strings)")
            """
        ),
        md("**`permutations(iterable, r)`**: ordered arrangements; `n! / (n - r)!` of them."),
        code(
            """
            podium = list(itertools.permutations(["Asha", "Ravi", "Meena"], 2))
            print(f"{len(podium)=}, first three: {podium[:3]}")
            """
        ),
        md(
            "**`combinations(iterable, r)`**: unordered selections without repeats; `n! / (r! (n - r)!)` of them."
        ),
        code(
            """
            combo_items = ["tea", "rice", "soap", "oil"]
            print(list(itertools.combinations(combo_items, 2)))
            """
        ),
        md(
            "**`combinations_with_replacement(iterable, r)`**: unordered selections where an item may repeat."
        ),
        code(
            """
            coin_values = [1, 2, 5]
            two_coin_amounts = sorted(
                {sum(pair) for pair in itertools.combinations_with_replacement(coin_values, 2)}
            )
            print(f"{list(itertools.combinations_with_replacement(coin_values, 2))=}")
            print(f"{two_coin_amounts=}")
            """
        ),
        md(
            """
            #### The itertools recipes and `more-itertools`

            The [itertools documentation](https://docs.python.org/3/library/itertools.html#itertools-recipes)
            ends with **recipes**: short functions built from the blocks above, meant to be copied
            into your code. Five of them:

            | Recipe | Does |
            | --- | --- |
            | `take(n, iterable)` | first `n` items as a list |
            | `nth(iterable, n, default=None)` | the item at index `n` |
            | `all_equal(iterable)` | are all items equal? |
            | `unique_everseen(iterable, key=None)` | unique items, first occurrence order |
            | `partition(predicate, iterable)` | (items where false, items where true) |
            """
        ),
        code(
            '''
            def take(n: int, iterable: Iterable[Any]) -> list[Any]:
                """Return the first n items as a list."""
                return list(itertools.islice(iterable, n))


            def nth(iterable: Iterable[Any], n: int, default: Any = None) -> Any:
                """Return the nth item or a default."""
                return next(itertools.islice(iterable, n, None), default)


            def all_equal(iterable: Iterable[Any]) -> bool:
                """Return True if all items are equal."""
                groups = itertools.groupby(iterable)
                return next(groups, True) and not next(groups, False)


            def unique_everseen(
                iterable: Iterable[Any], key: Callable[[Any], Any] | None = None
            ) -> Iterator[Any]:
                """Yield unique items, preserving first-seen order."""
                seen: set[Any] = set()
                for item in iterable:
                    marker = item if key is None else key(item)
                    if marker not in seen:
                        seen.add(marker)
                        yield item


            def partition(
                predicate: Callable[[Any], bool], iterable: Iterable[Any]
            ) -> tuple[Iterator[Any], Iterator[Any]]:
                """Split into (items where predicate is false, items where it is true)."""
                for_false, for_true = itertools.tee(iterable)
                return itertools.filterfalse(predicate, for_false), filter(predicate, for_true)
            '''
        ),
        md("Each recipe on a small input:"),
        code(
            """
            print(f"{take(3, itertools.count(1001))=}")
            print(f"{nth('ABCDE', 2)=}, {nth('AB', 9, 'none')=}")
            print(f"{all_equal([5, 5, 5])=}, {all_equal('aab')=}")
            print(f"{list(unique_everseen(['Tea', 'rice', 'TEA', 'Rice'], key=str.lower))=}")
            cheap, expensive = partition(lambda price: price > 500, [249, 640, 162, 980])
            print(f"{list(cheap)=}, {list(expensive)=}")
            """
        ),
        md(
            """
            The third-party [`more-itertools`](https://more-itertools.readthedocs.io/) package
            implements all the recipes and many more (`chunked`, `windowed`, `peekable`, `first`,
            `one`, `spy`, …). It is installed in Phase 4 (`uv add more-itertools`), so the next
            cell checks whether it is available and skips cleanly if not.
            """
        ),
        code(
            """
            if importlib.util.find_spec("more_itertools") is not None:
                import more_itertools

                print(f"{more_itertools.first([249, 640])=}")
                print(f"{list(more_itertools.chunked(range(7), 3))=}")
            else:
                print("more-itertools is not installed (it is added in Phase 4); skipped")
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.13."""
    return [
        md(
            """
            ### Lab 1.13

            Seven exercises. For each, replace the `raise NotImplementedError` in the stub, then
            run the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — re-iterable `Countdown`

            Unit 1.9.1 wrote `Countdown` with a separate `CountdownIterator` class. Rewrite it
            with **no iterator class**: make `__iter__` a generator method that yields
            `start, start - 1, …, 1`. Every loop must get a fresh generator, so the object can be
            looped over many times (and nested). `Countdown(0)` yields nothing;
            `Countdown(-1)` raises `ValueError` in `__init__`.
            """
        ),
        code(
            '''
            class Countdown:
                """Re-iterable countdown from start to 1."""

                def __init__(self, start: int) -> None:
                    raise NotImplementedError("Lab 1.13: implement Countdown")

                def __iter__(self) -> Iterator[int]:
                    raise NotImplementedError("Lab 1.13: implement Countdown.__iter__")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("counts down", lambda: list(Countdown(3)), [3, 2, 1]),
                    (
                        "re-iterable",
                        lambda: (lambda launch: (list(launch), list(launch)))(Countdown(2)),
                        ([2, 1], [2, 1]),
                    ),
                    (
                        "nested loops",
                        lambda: len([(a, b) for launch in [Countdown(3)] for a in launch for b in launch]),
                        9,
                    ),
                    ("zero", lambda: list(Countdown(0)), []),
                    ("negative", lambda: raised_error_name(lambda: Countdown(-1)), "ValueError"),
                    ("__iter__ is a generator", lambda: inspect.isgenerator(iter(Countdown(3))), True),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 2 — `read_log_records(path)`

            A **generator function** that opens the log file (UTF-8, with `with`) and yields one
            dict per record line, `{"date", "time", "level", "message"}`, using
            `line.split(maxsplit=3)` (the format of `parse_log_line` from Unit 1.4.7). Strip each
            line; skip blank lines, lines starting with `#`, and lines with fewer than four
            fields. It must be lazy: the file is opened only when iteration starts, and read one
            line at a time.
            """
        ),
        code(
            '''
            def read_log_records(path: Path) -> Iterator[dict[str, str]]:
                """Yield {"date", "time", "level", "message"} for each record line of the file."""
                raise NotImplementedError("Lab 1.13: implement read_log_records()")
            '''
        ),
        md(
            """
            Run the checks. The cell writes a six-line sample log (with a comment, a blank line and
            a malformed line) to `scratch_dir`.
            """
        ),
        code(
            """
            SAMPLE_LOG_TEXT = (
                "# service log\\n"
                "2026-11-05 09:30:01 INFO user asha logged in\\n"
                "\\n"
                "2026-11-05 09:30:05 ERROR payment failed: card declined\\n"
                "garbage line\\n"
                "2026-11-05 09:31:00 WARNING disk 91% full\\n"
            )
            sample_log_path = scratch_dir / "unit_1_13_sample.log"
            sample_log_path.write_text(SAMPLE_LOG_TEXT, encoding="utf-8")
            missing_log_path = scratch_dir / "unit_1_13_missing.log"
            run_checks(
                [
                    ("record count", lambda: len(list(read_log_records(sample_log_path))), 3),
                    (
                        "first record",
                        lambda: next(read_log_records(sample_log_path)),
                        {
                            "date": "2026-11-05",
                            "time": "09:30:01",
                            "level": "INFO",
                            "message": "user asha logged in",
                        },
                    ),
                    (
                        "levels",
                        lambda: [r["level"] for r in read_log_records(sample_log_path)],
                        ["INFO", "ERROR", "WARNING"],
                    ),
                    ("is a generator", lambda: inspect.isgenerator(read_log_records(sample_log_path)), True),
                    (
                        "lazy open",
                        lambda: raised_error_name(lambda: read_log_records(missing_log_path)),
                        "no error",
                    ),
                    (
                        "error on first next",
                        lambda: raised_error_name(lambda: next(read_log_records(missing_log_path))),
                        "FileNotFoundError",
                    ),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — `flatten(nested)`

            A recursive generator (use `yield from`) that yields the leaves of arbitrarily nested
            **lists and tuples**, left to right. Everything else, including strings and dicts, is
            a leaf and is yielded as is.
            """
        ),
        code(
            '''
            def flatten(nested: Iterable[Any]) -> Iterator[Any]:
                """Yield the leaves of nested lists and tuples."""
                raise NotImplementedError("Lab 1.13: implement flatten()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    ("deep", lambda: list(flatten([1, [2, [3, [4, (5, 6)]]], 7])), [1, 2, 3, 4, 5, 6, 7]),
                    (
                        "strings are leaves",
                        lambda: list(flatten(["tea", ["rice", ("soap",)]])),
                        ["tea", "rice", "soap"],
                    ),
                    ("dicts are leaves", lambda: list(flatten([{"a": 1}, [[]]])), [{"a": 1}]),
                    ("empty", lambda: list(flatten([[], [[]]])), []),
                    ("tuple at the top", lambda: list(flatten((1, (2, [3])))), [1, 2, 3]),
                    ("is a generator", lambda: inspect.isgenerator(flatten([])), True),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 4 — `running_average()` coroutine

            A generator used with `send`: after priming with `next()` (which yields `None`), each
            `send(number)` yields the average of **all numbers sent so far**, as a float. Each
            call to `running_average()` starts fresh.
            """
        ),
        code(
            '''
            def running_average() -> Generator[float | None, float]:
                """Receive numbers with send(); yield the running average."""
                raise NotImplementedError("Lab 1.13: implement running_average()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def averages_for(numbers: list[float]) -> tuple[float | None, list[float | None]]:
                """Prime a running_average and send numbers; return (priming value, averages)."""
                averager = running_average()
                priming_value = next(averager)
                return priming_value, [averager.send(number) for number in numbers]


            run_checks(
                [
                    ("averages", lambda: averages_for([10, 20, 60]), (None, [10.0, 15.0, 30.0])),
                    ("floats", lambda: averages_for([1, 2])[1], [1.0, 1.5]),
                    ("independent", lambda: (averages_for([100])[1], averages_for([2])[1]), ([100.0], [2.0])),
                    ("is a generator", lambda: inspect.isgenerator(running_average()), True),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — `paginate(fetch_page)`

            `fetch_page(page_number)` returns a list of items (pages are numbered from 1) and an
            **empty list** after the last page, like a paginated API. Write a generator that
            yields every item of every page, one at a time, and fetches a page **only when the
            consumer needs its first item**.
            """
        ),
        code(
            '''
            def paginate(fetch_page: Callable[[int], list[Any]]) -> Iterator[Any]:
                """Yield items from pages 1, 2, … until fetch_page returns an empty list."""
                raise NotImplementedError("Lab 1.13: implement paginate()")
            '''
        ),
        md(
            """
            Run the checks. `make_fake_api(items, page_size)` returns a `fetch_page` function that
            records every page number it is asked for.
            """
        ),
        code(
            '''
            def make_fake_api(items: list[Any], page_size: int) -> Callable[[int], list[Any]]:
                """Return fetch_page(page_number) serving items in pages; records requested pages."""
                requested_pages: list[int] = []

                def fetch_page(page_number: int) -> list[Any]:
                    requested_pages.append(page_number)
                    start = (page_number - 1) * page_size
                    return items[start : start + page_size]

                fetch_page.requested_pages = requested_pages
                return fetch_page


            def lazy_fetch_trace() -> tuple[list[str], list[int]]:
                """Take 3 items with page size 2: only pages 1 and 2 may be fetched."""
                fetch_page = make_fake_api(["A-1", "A-2", "A-3", "A-4", "A-5"], page_size=2)
                first_three = list(itertools.islice(paginate(fetch_page), 3))
                return first_three, fetch_page.requested_pages


            run_checks(
                [
                    (
                        "all items",
                        lambda: list(paginate(make_fake_api(list(range(7)), 3))),
                        [0, 1, 2, 3, 4, 5, 6],
                    ),
                    ("fetches lazily", lazy_fetch_trace, (["A-1", "A-2", "A-3"], [1, 2])),
                    ("no items", lambda: list(paginate(make_fake_api([], 3))), []),
                    (
                        "nothing fetched before iteration",
                        lambda: (lambda api: (paginate(api), api.requested_pages)[1])(make_fake_api([1], 1)),
                        [],
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 6 — `sliding_windows(iterable, size)`

            Yield tuples of `size` consecutive items: `sliding_windows("ABCD", 3)` →
            `("A", "B", "C")`, `("B", "C", "D")`. Fewer than `size` items → nothing. It must work on
            infinite iterators and keep at most `size` items in memory (hint: `deque(maxlen=size)`).
            `size < 1` raises `ValueError` (when iteration starts is fine).
            """
        ),
        code(
            '''
            def sliding_windows(iterable: Iterable[Any], size: int) -> Iterator[tuple[Any, ...]]:
                """Yield overlapping windows of size consecutive items."""
                raise NotImplementedError("Lab 1.13: implement sliding_windows()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    (
                        "windows of 3",
                        lambda: list(sliding_windows("ABCD", 3)),
                        [("A", "B", "C"), ("B", "C", "D")],
                    ),
                    ("size 1", lambda: list(sliding_windows([7, 8], 1)), [(7,), (8,)]),
                    ("too few items", lambda: list(sliding_windows([1, 2], 3)), []),
                    (
                        "infinite input",
                        lambda: list(itertools.islice(sliding_windows(itertools.count(), 2), 3)),
                        [(0, 1), (1, 2), (2, 3)],
                    ),
                    (
                        "moving average",
                        lambda: [sum(w) / 2 for w in sliding_windows([10, 20, 40], 2)],
                        [15.0, 30.0],
                    ),
                    ("size 0", lambda: raised_error_name(lambda: list(sliding_windows([1], 0))), "ValueError"),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 7 — streaming analysis of a 1M-line log

            Write two functions:

            - `summarize_log(records)`: one pass over **any iterable** of record dicts (as yielded
              by `read_log_records`), returning
              `{"total": <record count>, "by_level": {level: count, …} sorted by level name,
              "first_error": <message of the first ERROR record, or None>}`. Do not build a list
              of the records.
            - `analyze_log_file(path)`: `summarize_log(read_log_records(path))`.

            The next cell provides `write_big_log(path, line_count)` (deterministic data),
            `analyze_log_file_eager(path)` (the same summary computed by loading the whole file
            into memory first, the pattern to avoid) and `peak_memory(function, *args)` (result
            and peak bytes, measured with `tracemalloc`). The check writes a 1 000 000-line log
            (about 45 MB), compares both versions, prints their peak memory, and deletes the
            file. It takes several seconds once your solution works.
            """
        ),
        code(
            '''
            LEVEL_PATTERN = (
                "INFO",
                "INFO",
                "DEBUG",
                "INFO",
                "WARNING",
                "INFO",
                "DEBUG",
                "INFO",
                "INFO",
                "ERROR",
            )


            def write_big_log(path: Path, line_count: int) -> None:
                """Write a comment, a blank line and line_count deterministic records."""
                with path.open("w", encoding="utf-8") as log_file:
                    log_file.write("# synthetic service log\\n\\n")
                    log_file.writelines(
                        f"2026-11-05 {index // 3600 % 24:02d}:{index // 60 % 60:02d}:{index % 60:02d} "
                        f"{LEVEL_PATTERN[index % 10]} request {index} handled\\n"
                        for index in range(line_count)
                    )


            def analyze_log_file_eager(path: Path) -> dict[str, Any]:
                """Reference summary that reads the whole file into memory first."""
                all_lines = path.read_text(encoding="utf-8").splitlines()
                level_counts: Counter[str] = Counter()
                first_error = None
                for line in all_lines:
                    fields = line.strip().split(maxsplit=3)
                    if len(fields) < 4 or fields[0].startswith("#"):
                        continue
                    level_counts[fields[2]] += 1
                    if fields[2] == "ERROR" and first_error is None:
                        first_error = fields[3]
                return {
                    "total": level_counts.total(),
                    "by_level": dict(sorted(level_counts.items())),
                    "first_error": first_error,
                }


            def peak_memory(function: Callable[..., Any], *args: Any) -> tuple[Any, int]:
                """Return (function(*args), peak traced bytes during the call)."""
                tracemalloc.start()
                try:
                    result = function(*args)
                    return result, tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
            '''
        ),
        md("Write your two functions here."),
        code(
            '''
            def summarize_log(records: Iterable[dict[str, str]]) -> dict[str, Any]:
                """Return {"total", "by_level", "first_error"} in a single pass over records."""
                raise NotImplementedError("Lab 1.13: implement summarize_log()")


            def analyze_log_file(path: Path) -> dict[str, Any]:
                """Stream the file through read_log_records into summarize_log."""
                raise NotImplementedError("Lab 1.13: implement analyze_log_file()")
            '''
        ),
        md("Run the checks."),
        code(
            '''
            def streaming_vs_eager() -> tuple[Any, ...]:
                """Analyze a 1M-line log both ways; return the comparison."""
                big_log_path = scratch_dir / "unit_1_13_big.log"
                try:
                    write_big_log(big_log_path, 1_000_000)
                    streamed, streaming_peak = peak_memory(analyze_log_file, big_log_path)
                    eager, eager_peak = peak_memory(analyze_log_file_eager, big_log_path)
                    print(f"  peak memory: streaming {streaming_peak / 1e3:,.0f} kB", end=", ")
                    print(f"eager {eager_peak / 1e6:,.0f} MB")
                    return (
                        streamed == eager,
                        streamed["total"],
                        streamed["by_level"],
                        streamed["first_error"],
                        streaming_peak * 20 < eager_peak,
                    )
                finally:
                    big_log_path.unlink(missing_ok=True)


            small_records = [
                {"date": "d", "time": "t", "level": "WARNING", "message": "slow"},
                {"date": "d", "time": "t", "level": "ERROR", "message": "first failure"},
                {"date": "d", "time": "t", "level": "ERROR", "message": "second failure"},
            ]
            run_checks(
                [
                    (
                        "small input",
                        lambda: summarize_log(small_records),
                        {"total": 3, "by_level": {"ERROR": 2, "WARNING": 1}, "first_error": "first failure"},
                    ),
                    ("accepts an iterator", lambda: summarize_log(iter(small_records))["total"], 3),
                    (
                        "no records",
                        lambda: summarize_log([]),
                        {"total": 0, "by_level": {}, "first_error": None},
                    ),
                    (
                        "1M lines: same result, 20x less memory",
                        streaming_vs_eager,
                        (
                            True,
                            1_000_000,
                            {"DEBUG": 200_000, "ERROR": 100_000, "INFO": 600_000, "WARNING": 100_000},
                            "request 9 handled",
                            True,
                        ),
                    ),
                ]
            )
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.13."""
    return [
        md(
            """
            ### Recap — Unit 1.13

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Iterable vs iterator | Iterables give fresh iterators; iterators are single use (`iter(it) is it`) | `Symbol.iterator` / iterator objects |
            | Custom iterators | Keep the position in a separate iterator object; `__getitem__` is the legacy fallback | `[Symbol.iterator]()` returning a new object |
            | Generator functions | `yield` makes a lazy iterator; states via `getgeneratorstate`; frame in `gi_frame` | `function*` |
            | Generator `return` | The value rides on `StopIteration.value` | `{value, done: true}` |
            | Generator expressions | `(x for x in data)`: single use, constant memory; first iterable evaluated eagerly | iterator helpers |
            | Lazy pipelines | Chain generators; pull-based, one item at a time, stops early | streams |
            | `yield from` | Delegates iteration, recursion made easy, returns the sub-generator's value | `yield*` |
            | Two-way generators | `send` (prime first), `throw`, `close` → `GeneratorExit`; clean up in `finally` | `next(v)`, `throw`, `return` |
            | Generators → async | PEP 255 → 342 → 380 → 492: coroutines are driven with `send`, like generators | `async` / `await` |
            | `itertools` | Infinite, terminating and combinatoric building blocks; `groupby` needs sorted input | — |
            | Recipes / `more-itertools` | Copy recipes from the docs, or install `more-itertools` (Phase 4) | lodash |

            **Further reading**

            - [Glossary: iterable](https://docs.python.org/3/glossary.html#term-iterable),
              [iterator](https://docs.python.org/3/glossary.html#term-iterator),
              [generator](https://docs.python.org/3/glossary.html#term-generator)
            - [Iterator types](https://docs.python.org/3/library/stdtypes.html#iterator-types),
              [generator expressions](https://docs.python.org/3/reference/expressions.html#generator-expressions),
              [yield expressions](https://docs.python.org/3/reference/expressions.html#yield-expressions)
            - [Functional programming HOWTO](https://docs.python.org/3/howto/functional.html),
              [`itertools`](https://docs.python.org/3/library/itertools.html) and its
              [recipes](https://docs.python.org/3/library/itertools.html#itertools-recipes),
              [`more-itertools`](https://more-itertools.readthedocs.io/)
            - [`inspect.getgeneratorstate`](https://docs.python.org/3/library/inspect.html#inspect.getgeneratorstate),
              [coroutine objects](https://docs.python.org/3/reference/datamodel.html#coroutine-objects)
            - [PEP 234 — Iterators](https://peps.python.org/pep-0234/),
              [PEP 255 — Simple generators](https://peps.python.org/pep-0255/),
              [PEP 289 — Generator expressions](https://peps.python.org/pep-0289/)
            - [PEP 342 — Coroutines via enhanced generators](https://peps.python.org/pep-0342/),
              [PEP 380 — `yield from`](https://peps.python.org/pep-0380/),
              [PEP 492 — `async` and `await`](https://peps.python.org/pep-0492/),
              [PEP 525 — Asynchronous generators](https://peps.python.org/pep-0525/)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.13 and Lab 1.13."""
    return [
        *_overview_cells(),
        *_iterable_iterator_cells(),
        *_custom_iterator_cells(),
        *_generator_function_cells(),
        *_generator_expression_cells(),
        *_pipeline_cells(),
        *_yield_from_cells(),
        *_two_way_cells(),
        *_async_bridge_cells(),
        *_itertools_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
