"""Unit 1.7 — Copying: Shallow Copies, Deep Copies and Structured Clones (with Lab 1.7)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import copy
import datetime as dt
import json
import socket
import sys
import threading
import timeit
import tracemalloc
import types
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
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
PAISE = Decimal("0.01")
print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.7 — Copying: Shallow Copies, Deep Copies and Structured Clones

            **Objectives**

            - Tell an alias from a copy, and prove which one you have with `is`.
            - Make shallow copies of lists, dicts and sets in every idiomatic way, and predict
              which inner objects they still share.
            - Use `copy.deepcopy`, explain its memo dict, and customize copying with `__copy__`
              and `__deepcopy__`.
            - Know what cannot be copied and what copying costs.
            - Replace defensive copies with immutable snapshots (tuples, `frozenset`,
              `frozendict`) where you can.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `const b = a` | `b = a` | Same: both names point at one object (an alias) |
            | `[...items]`, `items.slice()` | `items.copy()`, `items[:]`, `list(items)` | Shallow in both: nested objects are shared |
            | `{...config}`, `Object.assign({}, config)` | `config.copy()`, `{**config}`, `dict(config)` | Shallow in both |
            | `structuredClone(value)` | `copy.deepcopy(value)` | `deepcopy` keeps class instances and copies functions by reference; `structuredClone` drops prototypes and rejects functions |
            | `JSON.parse(JSON.stringify(x))` | `json.loads(json.dumps(x))` | Wrong in both: Python loses tuples, sets, `Decimal`, datetimes and int keys |
            | `Object.freeze(obj)` | `tuple`, `frozenset`, `frozendict` | Python's frozen types are real immutable types, not a flag on an object |

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _assignment_cells() -> list[NotebookNode]:
    """1.7.1 Assignment vs copy."""
    return [
        md(
            """
            ### 1.7.1 Assignment vs copy

            Unit 1.2 showed that assignment **never copies**: `b = a` binds a second name to the
            same object. Changes made through either name are visible through both, because there
            is only one object. A copy is a **new** object, made by an explicit call.

            The next cell compares an alias with a copy. Equal `id()` values mean the same object
            (the cell compares ids instead of printing them, since the numbers change every run).
            """
        ),
        code(
            """
            cart_items = ["tea", "rice"]
            same_cart = cart_items  # alias: a second name, no new object
            copied_cart = cart_items.copy()  # a new list holding the same elements

            same_cart.append("ghee")
            print(f"{cart_items=}")
            print(f"{copied_cart=}")
            print(f"{id(same_cart) == id(cart_items)=}, {same_cart is cart_items=}")
            print(f"{id(copied_cart) == id(cart_items)=}, {copied_cart is cart_items=}")
            print(f"{copied_cart == ['tea', 'rice']=}  (equal values, different object)")
            """
        ),
        md(
            """
            Passing an object to a function is also assignment (the parameter is a new name for
            the caller's object, 1.2.3), so a function that mutates its argument changes the
            caller's data. That is the most common reason to copy.
            """
        ),
        code(
            '''
            def add_free_gift(order_items: list[str]) -> list[str]:
                """Append a gift item and return the list (mutates the argument!)."""
                order_items.append("free-sample")
                return order_items


            customer_order = ["tea"]
            gifted_order = add_free_gift(customer_order)
            print(f"{customer_order=}  (the caller's list changed)")
            print(f"{gifted_order is customer_order=}")

            customer_order = ["tea"]
            gifted_copy = add_free_gift(customer_order.copy())
            print(f"{customer_order=}, {gifted_copy=}  (copy passed in, caller untouched)")
            '''
        ),
    ]


def _shallow_cells() -> list[NotebookNode]:
    """1.7.2 Shallow copies."""
    return [
        md(
            """
            ### 1.7.2 Shallow copies

            A **shallow copy** builds a new outer container and fills it with references to the
            **same** element objects. Every built-in container has several spellings:

            | Container | Ways to shallow-copy |
            | --- | --- |
            | `list` | `items.copy()`, `items[:]`, `list(items)`, `copy.copy(items)` |
            | `dict` | `config.copy()`, `{**config}`, `dict(config)`, `copy.copy(config)` |
            | `set` | `tags.copy()`, `set(tags)`, `copy.copy(tags)` |

            Each of the next cells shows one spelling, and checks that the copy is a new object
            (`is not`) whose elements are the same objects (`is`).

            **`list.copy()`**: the explicit method, the clearest choice for lists.
            """
        ),
        code(
            """
            price_rows = [[60, 40], [30, 45]]
            rows_copy = price_rows.copy()
            print(f"{rows_copy == price_rows=}, {rows_copy is price_rows=}")
            print(f"{rows_copy[0] is price_rows[0]=}  (inner lists are shared)")
            """
        ),
        md(
            "**`[:]`**: a full slice; every slice of a list is a new list (Unit 1.5). Common in older code."
        ),
        code(
            """
            price_rows = [[60, 40], [30, 45]]
            rows_copy = price_rows[:]
            print(f"{rows_copy is price_rows=}, {rows_copy[1] is price_rows[1]=}")
            """
        ),
        md(
            "**`list(x)`**: the constructor copies **any** iterable into a new list (a tuple, a set, a generator)."
        ),
        code(
            """
            price_rows = [[60, 40], [30, 45]]
            rows_copy = list(price_rows)
            rows_from_tuple = list(((60, 40), (30, 45)))
            print(f"{rows_copy is price_rows=}, {rows_copy[0] is price_rows[0]=}")
            print(f"{rows_from_tuple=}  (outer type converted, inner tuples shared)")
            """
        ),
        md("**`dict.copy()`**: a new dict with the same key and value objects."),
        code(
            """
            stock_levels = {"tea": [5, 3], "rice": [9]}
            stock_copy = stock_levels.copy()
            print(f"{stock_copy is stock_levels=}, {stock_copy['tea'] is stock_levels['tea']=}")
            """
        ),
        md(
            "**`{**d}`**: dict unpacking into a literal (like JS spread). It is a copy that can also add or override keys."
        ),
        code(
            """
            stock_levels = {"tea": [5, 3], "rice": [9]}
            stock_copy = {**stock_levels, "ghee": [2]}
            print(f"{stock_copy=}")
            print(f"{stock_copy is stock_levels=}, {stock_copy['tea'] is stock_levels['tea']=}")
            """
        ),
        md(
            "**`set.copy()`**: a new set. Set elements are hashable, usually immutable, so a shallow copy of a set is normally all you need."
        ),
        code(
            """
            ticket_numbers = {101, 102, 103}
            tickets_copy = ticket_numbers.copy()
            tickets_copy.add(104)
            print(f"{sorted(ticket_numbers)=}, {sorted(tickets_copy)=}")
            print(f"{tickets_copy is ticket_numbers=}")
            """
        ),
        md(
            """
            **`copy.copy(x)`**: the generic shallow copy for any object. For built-in containers
            it calls their own copy; for class instances it builds a new instance and copies the
            attribute **dict** (shallowly). Immutable objects (`int`, `str`, `tuple`) come back
            unchanged, because a copy of an immutable object is pointless.
            """
        ),
        code(
            '''
            class Basket:
                """A tiny class to show copy.copy on instances."""

                def __init__(self, owner: str, items: list[str]) -> None:
                    self.owner = owner
                    self.items = items


            asha_basket = Basket("asha", ["tea"])
            basket_copy = copy.copy(asha_basket)
            print(f"{basket_copy is asha_basket=}, {basket_copy.items is asha_basket.items=}")
            print(f"{copy.copy([1, 2]) == [1, 2]=}, {copy.copy({'a': 1}) == {'a': 1}=}")
            point = (3, 4)
            print(f"{copy.copy(point) is point=}, {copy.copy('dosa') == 'dosa'=}  (immutables)")
            '''
        ),
        md(
            """
            **The outer container is new; inner objects are shared.** This is the trap. A nested
            config dict is copied shallowly, then a *nested* value is changed through the copy.
            The top-level key change stays local, but the nested change leaks into the original.

            ```mermaid
            flowchart LR
                base["base_config (dict)"] --> db["{'host': ..., 'pool': [5, 10]}"]
                copy_["staging_config (new dict)"] --> db
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            base_config ----\\
                             +--> {"host": "db.local", "pool": [5, 10]}   (one shared dict)
            staging_config -/
            ```

            </details>
            """
        ),
        code(
            """
            base_config = {
                "app_name": "shop",
                "database": {"host": "db.local", "pool_sizes": [5, 10]},
            }
            staging_config = base_config.copy()
            staging_config["app_name"] = "shop-staging"  # top level: only the copy changes
            staging_config["database"]["host"] = "staging-db.local"  # nested: shared!
            staging_config["database"]["pool_sizes"].append(20)

            print(f"{base_config['app_name']=}")
            print(f"{base_config['database']=}  (the original changed too)")
            print(f"{staging_config['database'] is base_config['database']=}")
            """
        ),
        *predict_cells(
            snippet="""
            menu = {"breakfast": ["idli"], "lunch": ["thali"]}
            menu_copy = {**menu}
            menu_copy["breakfast"] += ["dosa"]
            menu_copy["lunch"] = menu_copy["lunch"] + ["curd"]
            print(menu)
            """,
            answer="""
            `{'breakfast': ['idli', 'dosa'], 'lunch': ['thali']}`. `+=` on a list **mutates** it
            in place (`list.__iadd__` is `extend`), and that list is shared with `menu`. Then
            `menu_copy["lunch"] + [...]` builds a **new** list and rebinds only the copy's key,
            so `menu["lunch"]` is untouched.
            """,
            proof="""
            menu = {"breakfast": ["idli"], "lunch": ["thali"]}
            menu_copy = {**menu}
            menu_copy["breakfast"] += ["dosa"]
            menu_copy["lunch"] = menu_copy["lunch"] + ["curd"]
            print(menu)
            print(f"{menu_copy['lunch'] is menu['lunch']=}")
            """,
        ),
    ]


def _deep_cells() -> list[NotebookNode]:
    """1.7.3 Deep copies."""
    return [
        md(
            """
            ### 1.7.3 Deep copies

            `copy.deepcopy(x)` copies the container **and, recursively, everything it contains**,
            so the result shares no mutable object with the original. Immutable atoms (`int`,
            `str`, `None`, functions, classes) are reused, since copying them gains nothing.

            The same nested config as in 1.7.2, copied deeply this time:
            """
        ),
        code(
            """
            base_config = {
                "app_name": "shop",
                "database": {"host": "db.local", "pool_sizes": [5, 10]},
            }
            staging_config = copy.deepcopy(base_config)
            staging_config["database"]["host"] = "staging-db.local"
            staging_config["database"]["pool_sizes"].append(20)

            print(f"{base_config['database']=}  (unchanged)")
            print(f"{staging_config['database']=}")
            print(f"{staging_config['database'] is base_config['database']=}")
            print(f"{staging_config['app_name'] is base_config['app_name']=}  (str reused)")
            """
        ),
        md(
            """
            **The memo dict.** `deepcopy` keeps a dictionary `memo` that maps
            `id(original) → copy` for every object it has already copied. Before copying an
            object it looks it up in `memo`. That gives two guarantees:

            1. **Shared references stay shared.** If one list appears twice in the original, the
               copy contains one new list, twice; not two independent lists.
            2. **Cycles terminate.** A structure that contains itself is copied once, and the
               inner reference points at the copy instead of recursing forever.

            First, shared references. `default_tags` appears under two keys:
            """
        ),
        code(
            """
            default_tags = ["new"]
            catalog = {"tea": default_tags, "rice": default_tags}
            catalog_copy = copy.deepcopy(catalog)

            print(f"{catalog_copy['tea'] is catalog_copy['rice']=}  (still one list in the copy)")
            print(f"{catalog_copy['tea'] is default_tags=}  (but a new one)")
            catalog_copy["tea"].append("sale")
            print(f"{catalog_copy=}")
            """
        ),
        md(
            """
            Then a cycle: a list that contains itself. Python prints it as `[...]`. A naive
            recursive copy would never end; `deepcopy` finds the list in `memo` the second time
            and reuses the copy it is building.
            """
        ),
        code(
            """
            self_referencing = ["start"]
            self_referencing.append(self_referencing)
            print(f"{self_referencing=}")

            cycle_copy = copy.deepcopy(self_referencing)
            print(f"{cycle_copy=}")
            print(f"{cycle_copy[1] is cycle_copy=}  (the copy points at itself)")
            print(f"{cycle_copy is self_referencing=}")
            """
        ),
        md(
            """
            #### Under the hood: inspecting the memo

            You can pass your own `memo` dict and look at it afterwards. Keys are `id()` values of
            the originals (not printed, they change per run), values are their copies. There is
            also one bookkeeping entry: `memo[id(memo)]` holds a list that keeps the originals
            alive while copying, so their ids cannot be reused mid-copy.
            """
        ),
        code(
            """
            shared_pool = [5, 10]
            nested_settings = {"primary": shared_pool, "replica": shared_pool}
            copy_memo: dict[int, Any] = {}
            settings_copy = copy.deepcopy(nested_settings, copy_memo)

            print(f"{len(copy_memo)=}")
            print(f"{copy_memo[id(shared_pool)] is settings_copy['primary']=}")
            print(f"{copy_memo[id(nested_settings)] is settings_copy=}")
            print(f"{id(copy_memo) in copy_memo=}, {type(copy_memo[id(copy_memo)]).__name__=}")
            """
        ),
    ]


def _custom_copy_cells() -> list[NotebookNode]:
    """1.7.4 Customizing copies."""
    return [
        md(
            """
            ### 1.7.4 Customizing copies

            A class can control both kinds of copy:

            | Hook | Called by | Must return |
            | --- | --- | --- |
            | `__copy__(self)` | `copy.copy(obj)` | the shallow copy |
            | `__deepcopy__(self, memo)` | `copy.deepcopy(obj)` | the deep copy; pass `memo` on to nested `deepcopy` calls |

            The main reason to customize is to **share expensive read-only parts on purpose**: a
            large lookup table, a compiled regex, a connection pool. Copying them is slow and
            pointless, so the hook copies only the per-object state.

            The next cell defines `PriceList`, which holds a big read-only `tax_table` and a small
            mutable `overrides` dict. `__copy__` gives the copy its own `overrides` dict but keeps
            the same table.
            """
        ),
        code(
            '''
            class PriceList:
                """Prices with a large shared tax table and small per-copy overrides."""

                def __init__(self, tax_table: Mapping[str, int], overrides: dict[str, Any]) -> None:
                    self.tax_table = tax_table  # big and read-only: safe to share
                    self.overrides = overrides  # small and mutable: each copy needs its own

                def __copy__(self) -> PriceList:
                    print("  __copy__ called")
                    return PriceList(self.tax_table, dict(self.overrides))

                def __deepcopy__(self, memo: dict[int, Any]) -> PriceList:
                    print("  __deepcopy__ called")
                    return PriceList(self.tax_table, copy.deepcopy(self.overrides, memo))


            gst_table = types.MappingProxyType({f"hsn-{code}": 18 for code in range(10_000)})
            store_prices = PriceList(gst_table, {"tea": 249})
            print("shallow:")
            shallow_prices = copy.copy(store_prices)
            print(f"  {shallow_prices.tax_table is store_prices.tax_table=}")
            print(f"  {shallow_prices.overrides is store_prices.overrides=}")
            '''
        ),
        md(
            """
            `__deepcopy__` receives the memo and **must** pass it to every nested `deepcopy`
            call; otherwise shared references and cycles inside the object are not handled. Here
            the `overrides` dict holds lists (so it needs a real deep copy), while the 10 000-row
            table is still shared on purpose.
            """
        ),
        code(
            """
            store_prices = PriceList(gst_table, {"tea": 249, "combo": 0})
            store_prices.overrides["bundle_skus"] = ["tea", "rice"]
            print("deep:")
            deep_prices = copy.deepcopy(store_prices)
            print(f"  {deep_prices.tax_table is store_prices.tax_table=}  (shared on purpose)")
            print(f"  {deep_prices.overrides is store_prices.overrides=}")
            bundle_original = store_prices.overrides["bundle_skus"]
            print(f"  {deep_prices.overrides['bundle_skus'] is bundle_original=}")
            """
        ),
        md(
            """
            > **Note:** without these hooks, `copy` falls back to the pickle protocol
            > (`__reduce_ex__`), which for a plain class means "new instance + copy of
            > `__dict__`". Classes that define `__getstate__` / `__setstate__` for pickling get the
            > same behaviour for copies. Python 3.13 added `copy.replace(obj, **changes)` for
            > "copy with some fields changed"; it is covered with dataclasses in Phase 2.

            The last cell of this section shows the default (no hooks): a deep copy of an instance
            copies its `__dict__`, so every attribute is duplicated, including the big table.
            """
        ),
        code(
            '''
            class PlainPriceList:
                """The same data without copy hooks."""

                def __init__(self, tax_table: dict[str, int], overrides: dict[str, int]) -> None:
                    self.tax_table = tax_table
                    self.overrides = overrides


            plain_prices = PlainPriceList(dict(gst_table), {"tea": 249})
            plain_copy = copy.deepcopy(plain_prices)
            print(f"{plain_copy.tax_table is plain_prices.tax_table=}  (10 000 rows copied)")
            print(f"{plain_copy.__dict__.keys() == plain_prices.__dict__.keys()=}")
            '''
        ),
    ]


def _limits_cells() -> list[NotebookNode]:
    """1.7.5 Limits and cost."""
    return [
        md(
            """
            ### 1.7.5 Limits and cost

            Some objects **cannot** be copied, because they stand for something outside the
            Python heap (an OS lock, a file descriptor, a network connection) or for a paused
            computation (a generator frame). Copying the Python object would not copy the outside
            resource, so these types refuse: `copy` falls back to pickling and fails with
            `TypeError: cannot pickle ...`.

            | Object | Why it cannot be copied |
            | --- | --- |
            | `threading.Lock()` | a lock's state belongs to the OS; two "copies" could both be held |
            | open file | the descriptor and file position are OS state |
            | `socket.socket()` | a connection cannot be duplicated by copying memory |
            | generator | its suspended frame cannot be cloned (use `itertools.tee` to split one, 1.13) |

            Each of the next four cells tries `copy.deepcopy` on one of them.

            **A lock:**
            """
        ),
        code(
            """
            order_lock = threading.Lock()
            try:
                copy.deepcopy(order_lock)
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            """
        ),
        md("**An open file** (the unit's scratch file is written first, then opened for reading):"),
        code(
            """
            scratch_file = scratch_dir / "unit_1_7_copy_demo.txt"
            scratch_file.write_text("order 1001\\n", encoding="utf-8")
            with scratch_file.open(encoding="utf-8") as order_file:
                try:
                    copy.deepcopy(order_file)
                except TypeError as error:
                    print(f"{type(error).__name__}: {error}")
            """
        ),
        md("**A socket** (created but never connected, so no network is used):"),
        code(
            """
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as api_socket:
                try:
                    copy.deepcopy(api_socket)
                except TypeError as error:
                    print(f"{type(error).__name__}: {error}")
            """
        ),
        md("**A generator** (shallow `copy.copy` fails too; there is no frame-cloning at all):"),
        code(
            """
            order_numbers = (number for number in range(1001, 1004))
            for copy_function in (copy.copy, copy.deepcopy):
                try:
                    copy_function(order_numbers)
                except TypeError as error:
                    print(f"{copy_function.__name__}: {type(error).__name__}: {error}")
            """
        ),
        md(
            """
            **Cost.** A shallow copy touches only the outer container: O(n) pointer copies. A deep
            copy visits **every** object, keeps the memo dict, and dispatches on each object's
            type in Python code, so it is much slower and allocates much more. The next cell
            times both on 10 000 nested order records.

            > **Note:** the timings vary by machine and Python version; the ratio is what matters.
            """
        ),
        code(
            """
            order_records = [
                {"order_id": order_id, "customer": "asha", "lines": [{"sku": "TEA-500G", "qty": 2}]}
                for order_id in range(10_000)
            ]
            shallow_seconds = timeit.timeit(lambda: copy.copy(order_records), number=20) / 20
            deep_seconds = timeit.timeit(lambda: copy.deepcopy(order_records), number=3) / 3
            print(f"shallow copy: {shallow_seconds * 1000:8.3f} ms")
            print(f"deep copy:    {deep_seconds * 1000:8.3f} ms")
            print(f"deep is roughly {deep_seconds / shallow_seconds:,.0f}x slower")
            """
        ),
        md(
            """
            #### Under the hood: memory with `tracemalloc`

            `tracemalloc` measures the bytes allocated while each copy runs. The shallow copy
            allocates one new list (8 bytes per pointer plus a header); the deep copy allocates
            10 000 dicts, 10 000 inner lists and 10 000 inner dicts. Exact numbers vary by version.
            """
        ),
        code(
            '''
            def allocated_bytes(make_copy: Callable[[], object]) -> int:
                """Return the bytes still allocated by the object make_copy returns."""
                tracemalloc.start()
                before_bytes, _ = tracemalloc.get_traced_memory()
                copied_object = make_copy()
                after_bytes, _ = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                del copied_object
                return after_bytes - before_bytes


            shallow_bytes = allocated_bytes(lambda: copy.copy(order_records))
            deep_bytes = allocated_bytes(lambda: copy.deepcopy(order_records))
            print(f"shallow copy: {shallow_bytes:>12,} bytes")
            print(f"deep copy:    {deep_bytes:>12,} bytes")
            '''
        ),
    ]


def _js_bridge_cells() -> list[NotebookNode]:
    """1.7.6 JS bridge: structuredClone."""
    return [
        md(
            """
            ### 1.7.6 JS bridge: structuredClone

            | JavaScript | Python | Depth |
            | --- | --- | --- |
            | `[...items]`, `items.slice()` | `items.copy()`, `items[:]`, `list(items)` | shallow |
            | `{...config}`, `Object.assign({}, config)` | `config.copy()`, `{**config}`, `dict(config)` | shallow |
            | `structuredClone(value)` | `copy.deepcopy(value)` | deep |

            The biggest practical difference: `structuredClone` copies only "plain data". A class
            instance comes back as a plain object without its prototype (its methods are gone),
            and functions throw `DataCloneError`. `deepcopy` keeps the class, so methods still
            work, and copies functions and classes by reference.

            ```javascript
            class Cart { constructor() { this.items = [] } total() { return this.items.length } }
            const clone = structuredClone(new Cart())
            clone instanceof Cart   // false
            clone.total             // undefined
            ```

            The Python equivalent keeps everything:
            """
        ),
        code(
            '''
            class Cart:
                """A cart with a method, to show that deepcopy keeps the class."""

                def __init__(self, items: list[str], on_checkout: Callable[[], str]) -> None:
                    self.items = items
                    self.on_checkout = on_checkout

                def item_count(self) -> int:
                    """Return the number of items."""
                    return len(self.items)


            def send_receipt() -> str:
                """Pretend to send a receipt."""
                return "receipt sent"


            asha_cart = Cart(["tea", "rice"], send_receipt)
            cart_clone = copy.deepcopy(asha_cart)
            print(f"{type(cart_clone).__name__=}, {isinstance(cart_clone, Cart)=}")
            print(f"{cart_clone.item_count()=}, {cart_clone.items is asha_cart.items=}")
            print(f"{cart_clone.on_checkout is send_receipt=}  (functions are shared, not copied)")
            '''
        ),
        md(
            """
            **Why `json.loads(json.dumps(x))` is the wrong deep copy.** It is the Python version of
            the old `JSON.parse(JSON.stringify(x))` trick, and it fails for the same reason: JSON
            has only objects with string keys, arrays, strings, numbers, booleans and null. Every
            other type is either converted or rejected.

            | Value | After a JSON round trip |
            | --- | --- |
            | tuple | becomes a list |
            | set | `TypeError` (not serializable) |
            | `Decimal` | `TypeError` (or a lossy float with `default=float`) |
            | `datetime` | `TypeError` (or a string with `default=str`) |
            | int dict keys | become strings: `{1: ...}` → `{"1": ...}` |

            The next five cells show one failure each; `deepcopy` handles all of them.

            **Tuples become lists:**
            """
        ),
        code(
            """
            shipment = {"dimensions_cm": (30, 20, 10)}
            json_copy = json.loads(json.dumps(shipment))
            print(f"{json_copy=}, {type(json_copy['dimensions_cm']).__name__=}")
            print(f"{copy.deepcopy(shipment)=}")
            """
        ),
        md("**Sets are rejected:**"),
        code(
            """
            product = {"tags": {"organic", "vegan"}}
            try:
                json.dumps(product)
            except TypeError as error:
                print(f"{type(error).__name__}: {error}")
            print(f"{sorted(copy.deepcopy(product)['tags'])=}")
            """
        ),
        md(
            "**`Decimal` is rejected, and the usual workaround (`default=float`) silently loses exactness:**"
        ),
        code(
            """
            invoice = {"total": Decimal("1999.99")}
            print(f"plain dumps: {raised_error_name(lambda: json.dumps(invoice))}")
            float_round_trip = json.loads(json.dumps({"total": Decimal("0.1") * 3}, default=float))
            print(f"{float_round_trip=}  (a float now, not a Decimal)")
            print(f"{copy.deepcopy(invoice)=}")
            """
        ),
        md(
            "**Datetimes are rejected, and `default=str` turns them into strings that do not compare or add like dates:**"
        ),
        code(
            """
            delivery = {"due": dt.datetime(2026, 11, 3, 18, 30)}
            print(f"plain dumps: {raised_error_name(lambda: json.dumps(delivery))}")
            string_round_trip = json.loads(json.dumps(delivery, default=str))
            print(f"{string_round_trip=}, {type(string_round_trip['due']).__name__=}")
            print(f"{copy.deepcopy(delivery)=}")
            """
        ),
        md("**Int keys come back as strings, so lookups by the original key fail:**"),
        code(
            """
            stock_by_shelf = {1: "tea", 2: "rice"}
            json_copy = json.loads(json.dumps(stock_by_shelf))
            print(f"{json_copy=}")
            print(f"lookup json_copy[1]: {raised_error_name(lambda: json_copy[1])}")
            print(f"{copy.deepcopy(stock_by_shelf)[1]=}")
            """
        ),
    ]


def _snapshot_cells() -> list[NotebookNode]:
    """1.7.7 Immutable snapshots."""
    return [
        md(
            """
            ### 1.7.7 Immutable snapshots

            Defensive copying ("copy the input in case someone mutates it later") costs time and
            memory on every call. If the data is **immutable**, nobody can mutate it, so it can be
            shared freely and copying is unnecessary. `copy.copy` knows this and returns the same
            object for immutable built-ins.

            | Mutable | Immutable snapshot | Notes |
            | --- | --- | --- |
            | `list` | `tuple(items)` | immutable only if the elements are |
            | `set` | `frozenset(tags)` | hashable, usable as a dict key |
            | `dict` | `frozendict(config)` (*New in 3.15*) | hashable if the values are; `MappingProxyType` is a read-only *view* on older versions |

            The next cell takes a tuple snapshot of an order's line items and shows that
            `copy.copy` returns the same object, so passing it around costs nothing.
            """
        ),
        code(
            """
            live_line_items = ["TEA-500G", "RICE-5KG"]
            line_snapshot = tuple(live_line_items)
            live_line_items.append("GHEE-1L")
            print(f"{line_snapshot=}  (later appends do not reach the snapshot)")
            print(f"{copy.copy(line_snapshot) is line_snapshot=}")
            print(f"{copy.deepcopy(line_snapshot) is line_snapshot=}  (all elements immutable)")
            print(f"item assignment: {raised_error_name(lambda: line_snapshot.__setitem__(0, 'X'))}")
            """
        ),
        md(
            """
            A tuple is only as immutable as its contents. A tuple holding a list can still change
            through that list, and `deepcopy` must then copy it (it returns a new tuple).
            """
        ),
        code(
            """
            mixed_snapshot = ("asha", ["tea"])
            mixed_snapshot[1].append("rice")
            print(f"{mixed_snapshot=}  (the inner list changed)")
            print(f"{copy.deepcopy(mixed_snapshot) is mixed_snapshot=}")
            print(f"hash: {raised_error_name(lambda: hash(mixed_snapshot))}")
            """
        ),
        md(
            "**`frozenset`**: an immutable set of permissions that can be shared between users without copying, and used as a dict key."
        ),
        code(
            """
            EDITOR_PERMISSIONS = frozenset({"read", "write"})
            permissions_by_user = {"asha": EDITOR_PERMISSIONS, "ravi": EDITOR_PERMISSIONS}
            print(f"{copy.copy(EDITOR_PERMISSIONS) is EDITOR_PERMISSIONS=}")
            print(f"add: {raised_error_name(lambda: EDITOR_PERMISSIONS.add('admin'))}")
            role_names = {EDITOR_PERMISSIONS: "editor"}
            print(f"{role_names[frozenset({'write', 'read'})]=}")
            print(f"{sorted(permissions_by_user['ravi'])=}")
            """
        ),
        md(
            """
            **`frozendict`** (*New in 3.15*, PEP 814): an immutable dict. `copy.copy` returns the
            same object. `copy.deepcopy` still walks the values (they could be mutable), so it can
            return a new object; the point is that you do not need to call it at all.
            On older kernels the cell uses `types.MappingProxyType`, a read-only **view** that
            still changes if the dict behind it changes.
            """
        ),
        code(
            """
            settings_source = {"currency": "INR", "gst_percent": 18}
            if sys.version_info >= (3, 15):
                APP_SETTINGS = frozendict(settings_source)
                settings_source["gst_percent"] = 28  # the frozendict copied the data at creation
                print(f"{APP_SETTINGS=}")
                print(f"{copy.copy(APP_SETTINGS) is APP_SETTINGS=}")
                print(f"assign: {raised_error_name(lambda: APP_SETTINGS.__setitem__('currency', 'USD'))}")
                print(f"{hash(APP_SETTINGS) == hash(frozendict(gst_percent=18, currency='INR'))=}")
            else:
                read_only_view = types.MappingProxyType(settings_source)
                settings_source["gst_percent"] = 28
                print(f"frozendict needs Python 3.15; MappingProxyType view: {dict(read_only_view)=}")
            """
        ),
        md(
            """
            **Rule of thumb:** store configuration and reference data in immutable types from the
            start, and copy only the mutable working state (orders being edited, a cart being
            filled). Lab 1.7, exercise 2, needs a deep copy precisely because the orders are
            mutable nested dicts.
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.7."""
    return [
        md(
            """
            ### Lab 1.7

            Two exercises. For each, replace the `raise NotImplementedError` in the stub, then run
            the check cell. Until then the checks print FAIL; that is expected.

            #### Exercise 1 — `deep_merge(base, override)`

            Return a **new** dict that merges `override` into `base`:

            - a key only in one input is taken from that input;
            - if both values are dicts, they are merged recursively;
            - otherwise the `override` value wins (a list replaces a list, it is not appended).

            The function must **never mutate** its inputs, and the result must not share any
            mutable object with them: mutating the result afterwards must not change `base` or
            `override` (the checks use `is` to verify this). Use `copy.deepcopy` for values taken
            over unchanged.
            """
        ),
        code(
            '''
            def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
                """Return a new dict with override merged into base recursively."""
                raise NotImplementedError("Lab 1.7: implement deep_merge()")
            '''
        ),
        md(
            """
            The check cell builds fresh inputs for every case with `make_merge_inputs()`, and
            `merge_shares_nothing()` mutates the result to prove the inputs stay untouched.
            """
        ),
        code(
            '''
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
                    ("dict replaces scalar", lambda: deep_merge({"a": 1}, {"a": {"b": 2}}), {"a": {"b": 2}}),
                    ("scalar replaces dict", lambda: deep_merge({"a": {"b": 2}}, {"a": None}), {"a": None}),
                    (
                        "three levels deep",
                        lambda: deep_merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 3}}}),
                        {"a": {"b": {"c": 1, "d": 3}}},
                    ),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 2 — snapshot, discount, diff

            `apply_discounts_in_place` (given below) is "legacy" code: it changes unit prices
            **inside** the orders you pass. To report what it changed, take a snapshot first.

            1. `diff_orders(before, after)`: compare two order lists with the same shape and
               return a `PriceChange(order_id, sku, old_unit_price, new_unit_price)` for every
               line whose unit price differs, in order.
            2. `discount_and_diff(orders, discount_percent_by_sku)`: snapshot `orders` with
               `copy.deepcopy`, call `apply_discounts_in_place(orders, ...)` (so `orders` **is**
               changed, as the legacy code requires), and return `diff_orders(snapshot, orders)`.

            A shallow `orders.copy()` would make the diff empty, because the line dicts would be
            shared; one check guards against that.

            Run the next cell first: it defines `PriceChange`, `make_sample_orders()` (fresh data
            every call) and `apply_discounts_in_place`.
            """
        ),
        code(
            '''
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


            print(f"{len(make_sample_orders())=}")
            '''
        ),
        md("The two stubs:"),
        code(
            '''
            def diff_orders(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[PriceChange]:
                """Return a PriceChange for every line whose unit price differs."""
                raise NotImplementedError("Lab 1.7: implement diff_orders()")


            def discount_and_diff(
                orders: list[dict[str, Any]], discount_percent_by_sku: Mapping[str, int]
            ) -> list[PriceChange]:
                """Snapshot orders, apply discounts in place, return what changed."""
                raise NotImplementedError("Lab 1.7: implement discount_and_diff()")
            '''
        ),
        md("The check cell uses a 10% discount on tea and 5% on rice; ghee is not discounted."),
        code(
            '''
            sample_discounts = {"TEA-500G": 10, "RICE-5KG": 5}
            expected_changes = [
                PriceChange(1001, "TEA-500G", Decimal("249.00"), Decimal("224.10")),
                PriceChange(1002, "RICE-5KG", Decimal("525.50"), Decimal("499.23")),
            ]


            def orders_after_discount() -> list[dict[str, Any]]:
                """Run discount_and_diff on fresh orders and return the (mutated) orders."""
                live_orders = make_sample_orders()
                discount_and_diff(live_orders, sample_discounts)
                return live_orders


            def orders_with_rice_at_one_rupee() -> list[dict[str, Any]]:
                """Return fresh orders with the rice line edited by hand."""
                edited_orders = make_sample_orders()
                edited_orders[1]["lines"][0]["unit_price"] = Decimal("1.00")
                return edited_orders


            run_checks(
                [
                    (
                        "diff of identical orders",
                        lambda: diff_orders(make_sample_orders(), make_sample_orders()),
                        [],
                    ),
                    (
                        "discount_and_diff changes",
                        lambda: discount_and_diff(make_sample_orders(), sample_discounts),
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
            '''
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.7."""
    return [
        md(
            """
            ### Recap — Unit 1.7

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | Assignment | Binds another name to the same object; never copies | `const b = a` |
            | Shallow copy | New outer container, same inner objects | `[...a]`, `{...o}`, `Object.assign` |
            | Shallow spellings | `x.copy()`, `x[:]`, `list(x)`, `dict(x)`, `{**d}`, `set(x)`, `copy.copy(x)` | `slice()`, spread |
            | Nested data | Changes to inner objects leak through a shallow copy | same trap |
            | `copy.deepcopy` | Recursively copies everything mutable; immutables reused | `structuredClone` |
            | Memo dict | `id → copy`; keeps shared references shared and ends cycles | internal to `structuredClone` |
            | `__copy__` / `__deepcopy__(memo)` | Customize copies; share expensive read-only parts on purpose | no hook |
            | Uncopyable | Locks, files, sockets, generators raise `TypeError` | `DataCloneError` |
            | Cost | Deep copy is far slower and allocates per object | same |
            | Class instances | `deepcopy` keeps the class and methods | `structuredClone` drops the prototype |
            | JSON round trip | Loses tuples, sets, `Decimal`, datetimes, int keys | `JSON.parse(JSON.stringify())` |
            | Immutable snapshots | `tuple`, `frozenset`, `frozendict` need no defensive copy | `Object.freeze` (shallow) |

            **Further reading**

            - [`copy` — Shallow and deep copy operations](https://docs.python.org/3/library/copy.html)
            - [Programming FAQ: How do I copy an object?](https://docs.python.org/3/faq/programming.html#how-do-i-copy-an-object-in-python)
            - [`pickle` — object reduction (`__reduce_ex__`)](https://docs.python.org/3/library/pickle.html#object.__reduce_ex__)
            - [`json`](https://docs.python.org/3/library/json.html),
              [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html)
            - [`frozendict`](https://docs.python.org/3.15/library/stdtypes.html#frozendict),
              [PEP 814 — Add frozendict built-in type](https://peps.python.org/pep-0814/)
            - [MDN: `structuredClone()`](https://developer.mozilla.org/en-US/docs/Web/API/Window/structuredClone)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.7 and Lab 1.7."""
    return [
        *_overview_cells(),
        *_assignment_cells(),
        *_shallow_cells(),
        *_deep_cells(),
        *_custom_copy_cells(),
        *_limits_cells(),
        *_js_bridge_cells(),
        *_snapshot_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
