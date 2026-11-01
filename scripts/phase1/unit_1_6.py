"""Unit 1.6 — Collection Data Types II: Dictionaries, Sets and the collections Module (with Lab 1.6)."""

from nbformat import NotebookNode

from nb_builder import code, md, predict_cells

UNIT_SETUP_SOURCE = '''
import argparse
import array
import heapq
import json
import os
import re
import subprocess
import sys
import timeit
import tracemalloc
import types
from collections import ChainMap, Counter, OrderedDict, defaultdict, deque, namedtuple
from collections.abc import Callable, Hashable, Iterable, Mapping, MutableMapping
from decimal import Decimal
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


class LogEntry(NamedTuple):
    """One parsed line of an access log (as in 1.5.6)."""

    level: str
    message: str
    status_code: int = 200

    def is_error(self) -> bool:
        """Return True for ERROR entries and 5xx status codes."""
        return self.level == "ERROR" or self.status_code >= 500


print(f"{sys.version_info[:2]=}")
'''


def _overview_cells() -> list[NotebookNode]:
    """Unit opener and setup."""
    return [
        md(
            """
            ## Unit 1.6 — Collection Data Types II: Dictionaries, Sets and the collections Module

            **Objectives**

            - Explain how a `dict` is stored (compact hash table, probing, resizing, key sharing)
              and why lookups are O(1) on average.
            - State the hashing contract, and predict which keys collapse into one.
            - Use the complete `dict` and `set` APIs, including views, merge operators and
              in-place set algebra.
            - Choose between `dict`, `frozendict`, `MappingProxyType`, `set`, `frozenset` and the
              `collections` types (`deque`, `Counter`, `defaultdict`, `OrderedDict`, `ChainMap`).
            - Build stacks, queues, priority queues, graphs, tries and linked lists from built-ins.

            **JS bridge**

            | JavaScript concept | Python equivalent | The difference that bites |
            | --- | --- | --- |
            | `const prices = {dosa: 60}` | `prices = {"dosa": 60}` | Keys are expressions: a bare `dosa` is a variable name |
            | `prices.dosa`, `prices["dosa"]` | `prices["dosa"]` | No dot access; a missing key raises `KeyError` (use `.get`) |
            | `new Map()` with object keys | `dict` with any hashable key | Mutable keys (lists, dicts, sets) are rejected |
            | `obj[1]` is the same key as `obj["1"]` | `1` and `"1"` are different keys | But `1`, `1.0` and `True` are the **same** key |
            | `{...defaults, ...overrides}` | `{**defaults, **overrides}` or `defaults \\| overrides` | Both build a new dict; `\\|=` updates in place |
            | `new Set([1, 2])` | `{1, 2}` or `set(iterable)` | `{}` is an empty **dict**; use `set()` |
            | `a.union(b)` (ES2025 Set methods) | `a \\| b` or `a.union(b)` | Operators need sets on both sides; methods take any iterable |
            | `Object.freeze(obj)` | `frozendict(...)` / `types.MappingProxyType(...)` | `frozendict` is new in 3.15 and hashable |
            | `queue.shift()` | `queue.popleft()` on a `deque` | O(1); `list.pop(0)` is O(n) |
            | `(groups[k] ??= []).push(x)` | `groups.setdefault(k, []).append(x)` or `defaultdict(list)` | `defaultdict` inserts on every missing-key *read* |

            > **Note:** sets of strings print in an order that changes between interpreter runs
            > (string hashes are randomized per process, see 1.6.2). Demos print `sorted(...)` of
            > such sets so the saved outputs stay stable.

            The next cell is this unit's setup.
            """
        ),
        code(UNIT_SETUP_SOURCE),
    ]


def _dict_internals_cells() -> list[NotebookNode]:
    """1.6.1 Dictionaries — internals."""
    return [
        md(
            """
            ### 1.6.1 Dictionaries (`dict`) — internals

            Since CPython 3.6 a dict is a **compact hash table** built from two arrays:

            - a sparse **indices** array: one small integer per slot (1 byte each while the
              table has at most 128 slots), holding the position of an entry or "empty";
            - a dense **entries** array: `(hash, key, value)` rows, appended in insertion order.

            Looking up `key` hashes it, picks a slot with `hash & (table_size - 1)`, reads the
            entry index from that slot, and compares the stored hash and key. Because entries are
            appended, iteration simply walks the entries array, which is why **insertion order is
            guaranteed** (a language rule since 3.7). The split also saves memory: the wide rows
            are dense, and only the 1-byte indices are sparse.

            ```mermaid
            flowchart LR
                indices["indices (sparse, 8 slots)<br/>slot: 0 1 2 3 4 5 6 7<br/>value: - 1 - - 0 - 2 -"]
                entries["entries (dense, insertion order)<br/>0: hash, 'dosa', 60<br/>1: hash, 'idli', 40<br/>2: hash, 'vada', 30"]
                indices -- "slot = hash & 7<br/>value = entry position" --> entries
            ```

            <details><summary>ASCII fallback</summary>

            ```text
            indices (sparse)              entries (dense, in insertion order)
            slot  value                   pos  hash      key     value
            0     -                       0    h(dosa)   'dosa'  60
            1     1  ------------------>  1    h(idli)   'idli'  40
            2     -                       2    h(vada)   'vada'  30
            3     -
            4     0  ------------------>  (pos 0)
            5     -
            6     2  ------------------>  (pos 2)
            7     -
            ```

            </details>

            The next cell shows the order rules: replacing a value keeps the key's position;
            deleting and re-inserting moves the key to the end.
            """
        ),
        code(
            """
            menu_prices = {"dosa": 60, "idli": 40, "vada": 30}
            menu_prices["upma"] = 45
            menu_prices["dosa"] = 65  # replacing a value keeps the original position
            del menu_prices["idli"]
            menu_prices["idli"] = 40  # re-inserting goes to the end
            print(f"{list(menu_prices)=}")
            print(f"{menu_prices=}")
            """
        ),
        md(
            """
            **Open addressing with perturbed probing.** Two keys can land in the same slot. CPython
            does not chain them in a list; it probes other slots of the same table. The recurrence
            (from `Objects/dictobject.c`) mixes in the high bits of the hash, so keys that collide
            at first soon follow different paths:

            ```text
            perturb = hash
            slot = hash & mask
            while slot is taken by a different key:
                perturb >>= 5
                slot = (slot * 5 + perturb + 1) & mask
            ```

            The next cell runs that recurrence in pure Python. `hash(n)` is `n` for small
            non-negative ints, so the slots are the same on every machine. `12345` and `12353`
            both start in slot 1 of an 8-slot table (they differ by 8), then split apart.
            """
        ),
        code(
            '''
            def probe_sequence(hash_value: int, table_size: int, probe_count: int) -> list[int]:
                """Return the first slots CPython's dict tries for hash_value (table_size: power of 2)."""
                mask = table_size - 1
                perturb = hash_value
                slot = hash_value & mask
                tried_slots = [slot]
                for _ in range(probe_count - 1):
                    perturb >>= 5
                    slot = (slot * 5 + perturb + 1) & mask
                    tried_slots.append(slot)
                return tried_slots


            print(f"{probe_sequence(hash(12345), 8, 8)=}")
            print(f"{probe_sequence(hash(12353), 8, 8)=}")
            print(f"{probe_sequence(hash(1), 8, 8)=}  (perturb hits 0 after one shift)")
            '''
        ),
        md(
            """
            **Resizing.** A table is kept at most about two-thirds full, so probes stay short.
            When an insert would pass that limit, CPython allocates a bigger table and re-inserts
            every entry: an O(n) step that happens rarely enough for inserts to stay O(1)
            *amortized* (the same idea as `list` over-allocation in 1.5.2). Watch
            `sys.getsizeof` jump. The exact sizes vary by Python version and platform.
            """
        ),
        code(
            """
            growing_dict: dict[int, int] = {}
            previous_size = sys.getsizeof(growing_dict)
            print(f"0 keys: {previous_size} bytes")
            for key_count in range(1, 100):
                growing_dict[key_count] = key_count
                current_size = sys.getsizeof(growing_dict)
                if current_size != previous_size:
                    print(f"{key_count:>2} keys: {current_size:>5} bytes (table resized)")
                    previous_size = current_size
            """
        ),
        md(
            """
            #### Under the hood: key-sharing dicts (PEP 412)

            Every instance of a class keeps its attributes in a namespace dict. Most instances of
            one class have the **same attribute names**, so CPython stores the keys once per class
            and gives each instance only its values (a *split* or *key-sharing* dict; recent versions
            keep the values inside the object itself until someone asks for `__dict__`).

            `sys.getsizeof(instance.__dict__)` is misleading here (it reports a materialized dict),
            so the next cell uses `tracemalloc` to measure the memory of 10 000 objects of each
            kind. Expect instances to cost clearly less than plain dicts with the same three keys;
            the exact numbers vary by version.
            """
        ),
        code(
            '''
            class MenuItem:
                """A plain class: its instances share one key table (PEP 412)."""

                def __init__(self, name: str, price: int, is_veg: bool) -> None:
                    self.name = name
                    self.price = price
                    self.is_veg = is_veg


            def bytes_per_object(factory: Callable[[int], object], object_count: int = 10_000) -> float:
                """Return the average traced memory of object_count objects built by factory."""
                tracemalloc.start()
                kept_objects = [factory(number) for number in range(object_count)]
                traced_bytes, _peak_bytes = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                return traced_bytes / len(kept_objects)


            instance_bytes = bytes_per_object(lambda number: MenuItem(f"dish {number}", 60, True))
            dict_bytes = bytes_per_object(
                lambda number: {"name": f"dish {number}", "price": 60, "is_veg": True}
            )
            print(f"MenuItem instance: about {instance_bytes:.0f} bytes each")
            print(f"plain dict:        about {dict_bytes:.0f} bytes each")
            print(f"{instance_bytes < dict_bytes=}")
            '''
        ),
        md(
            """
            **Dict vs list membership.** `key in some_dict` hashes once and probes a slot or two;
            `value in some_list` compares against every item. The next cell searches 10 000 SKU
            codes for one that is missing (the worst case for the list). Timings vary by machine;
            the ratio is what matters.
            """
        ),
        code(
            """
            sku_codes = [f"SKU{number:05}" for number in range(10_000)]
            sku_lookup = dict.fromkeys(sku_codes, True)
            missing_sku = "SKU-MISSING"
            repeat_count = 200
            list_seconds = timeit.timeit(lambda: missing_sku in sku_codes, number=repeat_count)
            dict_seconds = timeit.timeit(lambda: missing_sku in sku_lookup, number=repeat_count)
            print(f"list membership: {list_seconds / repeat_count * 1e6:8.2f} µs per lookup")
            print(f"dict membership: {dict_seconds / repeat_count * 1e6:8.3f} µs per lookup")
            print(f"dict is about {list_seconds / dict_seconds:,.0f}x faster here (varies by machine)")
            """
        ),
    ]


def _hashing_cells() -> list[NotebookNode]:
    """1.6.2 Hashing."""
    return [
        md(
            """
            ### 1.6.2 Hashing

            `hash(obj)` returns an `int` computed by `obj.__hash__()`. An object is **hashable**
            when it has a hash that never changes during its lifetime **and** that agrees with
            `__eq__`: if `a == b` then `hash(a) == hash(b)` (the reverse need not hold; that is a
            collision). Dicts and sets rely on both halves: the hash picks the slot, `==` confirms
            the match.

            Integer hashes are deterministic (`hash(n) == n` for small ints, and `-1` is reserved
            as an error marker in C, so `hash(-1) == -2`). Equal tuples hash equally.
            """
        ),
        code(
            """
            print(f"{hash(42)=}, {hash(-1)=}, {hash(-2)=}")
            print(f"{hash((1, 'dosa')) == hash((1, 'dosa'))=}")
            print(f"{isinstance('dosa', Hashable)=}, {isinstance([], Hashable)=}")
            """
        ),
        md(
            """
            **The contract in practice.** Defining `__eq__` without `__hash__` sets `__hash__` to
            `None`, so instances become unhashable: Python refuses to guess a hash that agrees
            with your equality. The second class breaks the contract by hashing a field that
            changes; after the change the object sits in the wrong slot and the set can no longer
            find it.
            """
        ),
        code(
            '''
            class SkuCode:
                """Equal when the codes match; no __hash__, so it is unhashable."""

                def __init__(self, code: str) -> None:
                    self.code = code

                def __eq__(self, other: object) -> bool:
                    return isinstance(other, SkuCode) and self.code == other.code


            print(f"{SkuCode.__hash__=}")
            print(f"hash(SkuCode('A1')): {raised_error_name(lambda: hash(SkuCode('A1')))}")
            '''
        ),
        md("The broken version: the hash depends on a field that is later changed."),
        code(
            '''
            class MutableSkuCode(SkuCode):
                """Hashes a mutable field: breaks the hashing contract."""

                def __hash__(self) -> int:
                    return hash(self.code)


            tracked_sku = MutableSkuCode("A1")
            tracked_skus = {tracked_sku}
            tracked_sku.code = "B2"  # the stored hash is still hash("A1")
            print(f"{tracked_sku in tracked_skus=}  (looks in the slot for 'B2')")
            print(f"{MutableSkuCode('A1') in tracked_skus=}  (right slot, but == fails)")
            print(f"{len(tracked_skus)=}  (the object is still there, unreachable)")
            '''
        ),
        md(
            """
            **`1`, `1.0` and `True` are one key.** `True == 1 == 1.0`, so the language requires
            `hash(True) == hash(1) == hash(1.0)`. A dict treats them as the same key: the **first**
            key object is kept, the **last** value wins.
            """
        ),
        code(
            """
            print(f"{hash(1) == hash(1.0) == hash(True)=}")
            print(f"{1 == 1.0 == True=}")
            print(f"{ {1: 'int', True: 'bool'}=}")  # noqa: F601
            print(f"{len({1, 1.0, True})=}")  # noqa: B033
            """
        ),
        md("#### Predict the output: mixed numeric keys"),
        *predict_cells(
            snippet="""
            seat_labels = {1: "one", True: "yes", 1.0: "float one"}
            print(seat_labels)
            """,
            answer="""
            `{1: 'float one'}`. All three keys are equal and hash the same, so they are one key.
            The dict keeps the first key object (`1`) and stores each new value over the old
            one, so the last value (`'float one'`) wins.
            """,
            proof="""
            seat_labels = {1: "one", True: "yes", 1.0: "float one"}  # noqa: F601
            print(seat_labels)
            """,
        ),
        md(
            """
            **String-hash randomization.** `str` and `bytes` hashes use a random key chosen when
            the interpreter starts. Without it, an attacker who knows the hash function can send
            thousands of keys that all collide (for example as form fields or JSON keys), turning
            each dict insert into O(n) work: a **hash-flooding** denial of service (2011–2012,
            CVE-2012-1150). Since Python 3.4 the function is **SipHash** (PEP 456), a keyed hash
            designed against this attack (SipHash-2-4 at first, the faster SipHash-1-3 since
            3.11); `sys.hash_info.algorithm` names the variant.

            `PYTHONHASHSEED` controls the key: unset or `random` → a new key per process; an
            integer → a fixed key (useful only for reproducing a bug). The next cell starts child
            interpreters and compares their `hash("dosa")` values. It prints counts, never the
            hashes themselves, because those differ per run.
            """
        ),
        code(
            '''
            def string_hash_in_child(hash_seed: str | None) -> str:
                """Return hash("dosa") from a fresh interpreter run with the given PYTHONHASHSEED."""
                child_environment = {
                    name: value for name, value in os.environ.items() if name != "PYTHONHASHSEED"
                }
                if hash_seed is not None:
                    child_environment["PYTHONHASHSEED"] = hash_seed
                completed = subprocess.run(
                    [sys.executable, "-c", "print(hash('dosa'))"],
                    capture_output=True,
                    text=True,
                    env=child_environment,
                    check=True,
                )
                return completed.stdout.strip()


            random_seed_hashes = {string_hash_in_child(None) for _ in range(3)}
            fixed_seed_hashes = {string_hash_in_child("0") for _ in range(3)}
            print(f"distinct hash('dosa') values, 3 runs, random key:      {len(random_seed_hashes)}")
            print(f"distinct hash('dosa') values, 3 runs, PYTHONHASHSEED=0: {len(fixed_seed_hashes)}")
            print(f"{sys.hash_info.algorithm=}, {sys.hash_info.width=}")
            print(f"{sys.flags.hash_randomization=}")
            '''
        ),
        md(
            """
            **Unhashable types.** The mutable built-ins `list`, `dict`, `set` and `bytearray` have
            `__hash__ = None`. A `tuple` is hashable only if every item is, so `isinstance(...,
            Hashable)` can say yes while `hash()` still fails.
            """
        ),
        code(
            """
            print(f"list key:  {raised_error_name(lambda: {['rice']: 1})}")
            print(f"dict key:  {raised_error_name(lambda: {dict(): 1})}")
            print(f"set key:   {raised_error_name(lambda: {set(): 1})}")
            tuple_holding_list = ("rice", [1, 2])
            print(f"{isinstance(tuple_holding_list, Hashable)=}")
            print(f"hash(tuple_holding_list): {raised_error_name(lambda: hash(tuple_holding_list))}")
            """
        ),
        md(
            """
            **Tuple composite keys.** When a record is identified by several fields, use a tuple
            of them as the key: no string concatenation, no separator bugs.
            """
        ),
        code(
            """
            seat_bookings: dict[tuple[str, int, str], str] = {
                ("2026-11-01", 7, "A"): "Asha",
                ("2026-11-01", 7, "B"): "Ravi",
            }
            seat_bookings[("2026-11-02", 3, "A")] = "Meena"
            print(f"{seat_bookings[('2026-11-01', 7, 'B')]=}")
            print(f"{('2026-11-01', 7, 'C') in seat_bookings=}")
            print(f"{[seat for seat in seat_bookings if seat[0] == '2026-11-01']=}")
            """
        ),
        md(
            """
            **Collisions cost time.** The next class returns the same hash for every key. All keys
            land on the same probe path, so each insert compares against every earlier key:
            building the dict becomes O(n²). Compare it with the same class using a proper hash.
            Doubling the key count should roughly double the good time but roughly quadruple the
            bad one (timings vary by machine).
            """
        ),
        code(
            '''
            class ConstantHashKey:
                """A key whose hash is always 42, so every key collides."""

                def __init__(self, value: int) -> None:
                    self.value = value

                def __eq__(self, other: object) -> bool:
                    return isinstance(other, ConstantHashKey) and self.value == other.value

                def __hash__(self) -> int:
                    return 42


            class WellHashedKey(ConstantHashKey):
                """The same key with a hash that spreads values over the table."""

                def __hash__(self) -> int:
                    return hash(self.value)


            def build_seconds(key_class: type[ConstantHashKey], key_count: int) -> float:
                """Time building a dict of key_count keys of key_class."""
                return timeit.timeit(
                    lambda: {key_class(number): number for number in range(key_count)}, number=3
                )


            for key_count in (250, 500, 1000):
                good_seconds = build_seconds(WellHashedKey, key_count)
                bad_seconds = build_seconds(ConstantHashKey, key_count)
                print(
                    f"{key_count:>5} keys: good hash {good_seconds * 1e3:6.2f} ms, "
                    f"constant hash {bad_seconds * 1e3:8.2f} ms"
                )
            '''
        ),
        md(
            """
            **Python has no separate "hash" type.** JavaScript has `Object`, `Map` and libraries
            with "HashMap" classes; Java has `HashMap` and `Hashtable`. In Python the built-in
            `dict` *is* the hash map, and `set` is the hash set. The abstract interfaces live in
            `collections.abc` (`Mapping`, `MutableMapping`). A dict itself is not hashable, which
            is what `frozendict` (1.6.5) fixes.
            """
        ),
        code(
            """
            inventory = {"rice": 10}
            print(f"{type(inventory).__name__=}")
            print(f"{isinstance(inventory, Mapping)=}, {isinstance(inventory, MutableMapping)=}")
            print(f"{dict.__hash__ is None=}  (the hash map itself is not hashable)")
            """
        ),
    ]


def _dict_methods_cells() -> list[NotebookNode]:
    """1.6.3 Dictionary methods (complete API)."""
    return [
        md(
            """
            ### 1.6.3 Dictionary methods (complete API)

            This section teaches the API by task: access, modify, views, construction, copying.
            1.6.9 repeats every method as a short reference demo.

            **Access.** `d[key]` raises `KeyError` for a missing key. `get(key, default=None)`
            never raises. `in` tests **keys**, not values. A stored `0` or `""` is a real value,
            so `get` returns it rather than the default.
            """
        ),
        code(
            """
            stock_levels = {"rice": 12, "dal": 0}
            print(f"{stock_levels['rice']=}")
            print(f"missing key with []: {raised_error_name(lambda: stock_levels['ghee'])}")
            print(f"{stock_levels.get('ghee')=}, {stock_levels.get('ghee', 0)=}")
            print(f"{stock_levels.get('dal', 99)=}  (0 is stored, so no default)")
            print(f"{'dal' in stock_levels=}, {12 in stock_levels=}  (in checks keys)")
            """
        ),
        md(
            """
            `setdefault(key, default)` returns the value for `key`, inserting `default` first if
            the key is missing. It is the one-line "get or create" used for grouping. The default
            is evaluated on every call, even when the key exists.
            """
        ),
        code(
            """
            tags_by_dish: dict[str, list[str]] = {}
            tags_by_dish.setdefault("dosa", []).append("veg")
            tags_by_dish.setdefault("dosa", []).append("breakfast")
            tags_by_dish.setdefault("kebab", []).append("grill")
            print(f"{tags_by_dish=}")
            print(f"{stock_levels.setdefault('rice', 99)=}  (existing value returned, not replaced)")
            print(f"{stock_levels.setdefault('ghee', 3)=}, {stock_levels=}")
            """
        ),
        md(
            """
            **Modify.** `d[key] = value` inserts or replaces. `update` accepts a mapping, an
            iterable of `(key, value)` pairs, keyword arguments, or a mapping/pairs **plus**
            keywords; later values win.
            """
        ),
        code(
            """
            stock_levels = {"rice": 12}
            stock_levels["dal"] = 5
            stock_levels["rice"] = 10
            stock_levels.update({"ghee": 2})
            stock_levels.update([("salt", 7), ("tea", 3)])
            stock_levels.update(sugar=4, rice=8)
            stock_levels.update({"oil": 1}, oil=2)
            print(f"{stock_levels=}")
            """
        ),
        md(
            """
            **`|` and `|=`** (PEP 584, 3.9) merge dicts. `|` builds a new dict and needs a dict
            on both sides; `|=` updates in place and, like `update`, also accepts pairs. On
            duplicate keys the right side wins.
            """
        ),
        code(
            """
            default_settings = {"theme": "light", "page_size": 20}
            user_settings = {"page_size": 50}
            merged_settings = default_settings | user_settings
            print(f"{merged_settings=}")
            print(f"{default_settings=}  (unchanged by |)")
            default_settings |= [("language", "en")]
            print(f"{default_settings=}  (|= accepts pairs)")
            print(f"dict | list: {raised_error_name(lambda: default_settings | [('x', 1)])}")
            """
        ),
        md(
            """
            **Removing.** `pop(key, default)` removes and returns a value (`KeyError` without a
            default); `popitem()` removes the **last inserted** pair (LIFO); `del d[key]` raises
            `KeyError` if the key is missing; `clear()` empties the dict in place.
            """
        ),
        code(
            '''
            def delete_key(mapping: dict[str, int], key: str) -> None:
                """Run del mapping[key] (del is a statement, so it cannot go in a lambda)."""
                del mapping[key]


            shopping_basket = {"rice": 2, "dal": 1, "ghee": 1}
            print(f"{shopping_basket.pop('dal')=}, {shopping_basket.pop('salt', 0)=}")
            print(f"pop missing, no default: {raised_error_name(lambda: shopping_basket.pop('salt'))}")
            shopping_basket["tea"] = 3
            print(f"{shopping_basket.popitem()=}  (the last inserted pair)")
            delete_key(shopping_basket, "rice")
            print(f"{shopping_basket=}")
            print(f"del missing key: {raised_error_name(lambda: delete_key(shopping_basket, 'oil'))}")
            shopping_basket.clear()
            print(f"{shopping_basket=}, popitem on empty: {raised_error_name(shopping_basket.popitem)}")
            '''
        ),
        md(
            """
            **Views.** `keys()`, `values()` and `items()` return *views*: small objects that read
            the dict live, so later changes show through. They are not copies; wrap them in
            `list()` for a snapshot.
            """
        ),
        code(
            """
            menu_prices = {"dosa": 60, "idli": 40}
            menu_keys = menu_prices.keys()
            menu_items = menu_prices.items()
            menu_prices["vada"] = 30
            print(f"{menu_keys=}")
            print(f"{menu_items=}")
            print(f"{list(menu_prices.values())=}, {('idli', 40) in menu_items=}")
            """
        ),
        md(
            """
            `keys()` and `items()` views behave like sets: `&`, `|`, `-`, `^` work on them and
            return real `set` objects (and the right operand can be any iterable). `values()`
            views do not, because values need not be hashable or unique. The results are sets of
            strings, so they are printed sorted.
            """
        ),
        code(
            """
            store_a_stock = {"rice": 12, "dal": 5, "ghee": 2}
            store_b_stock = {"dal": 3, "salt": 9}
            print(f"{sorted(store_a_stock.keys() & store_b_stock.keys())=}")
            print(f"{sorted(store_a_stock.keys() - store_b_stock.keys())=}")
            print(f"{sorted(store_a_stock.keys() | store_b_stock.keys())=}")
            print(f"{sorted(store_a_stock.keys() ^ store_b_stock.keys())=}")
            print(f"{sorted(store_a_stock.keys() & ['dal', 'oil'])=}  (any iterable on the right)")
            print(f"values() & ...: {raised_error_name(lambda: store_a_stock.values() & {5})}")
            """
        ),
        md(
            """
            **Construction.** Five equivalent ways to build the same dict, plus `dict.fromkeys`
            (every key gets the same value). `zip(..., strict=True)` raises `ValueError` if the
            key and value lists have different lengths, instead of silently dropping items.
            """
        ),
        code(
            """
            from_literal = {"dosa": 60, "idli": 40}
            from_keywords = dict(dosa=60, idli=40)
            from_pairs = dict([("dosa", 60), ("idli", 40)])
            from_zip = dict(zip(["dosa", "idli"], [60, 40], strict=True))
            from_comprehension = {dish: price for dish, price in [("dosa", 60), ("idli", 40)]}
            print(f"{from_literal == from_keywords == from_pairs == from_zip == from_comprehension=}")
            print(f"{dict.fromkeys(['dosa', 'idli'], 0)=}")
            mismatched_zip = raised_error_name(lambda: dict(zip(["dosa"], [60, 40], strict=True)))
            print(f"zip with different lengths: {mismatched_zip}")
            """
        ),
        md("#### Predict the output: the `dict.fromkeys` shared-value trap"),
        *predict_cells(
            snippet="""
            orders_by_table = dict.fromkeys(["T1", "T2"], [])
            orders_by_table["T1"].append("dosa")
            print(orders_by_table)
            """,
            answer="""
            `{'T1': ['dosa'], 'T2': ['dosa']}`. `fromkeys` evaluates `[]` **once** and stores that
            same list object under every key, so appending through one key shows under all of
            them. It is the dict version of `[[0] * 3] * 3` from Lab 1.5.
            """,
            proof="""
            orders_by_table = dict.fromkeys(["T1", "T2"], [])
            orders_by_table["T1"].append("dosa")
            print(orders_by_table)
            print(f"{orders_by_table['T1'] is orders_by_table['T2']=}")
            """,
        ),
        md(
            """
            The fix: a comprehension evaluates `[]` once **per key**. (`dict.fromkeys` is still
            fine with immutable values such as `0`, `None` or `False`.)
            """
        ),
        code(
            """
            orders_by_table = {table: [] for table in ["T1", "T2"]}
            orders_by_table["T1"].append("dosa")
            print(f"{orders_by_table=}")
            """
        ),
        md(
            """
            **Copying.** `copy()` and `{**d}` both make a **shallow** copy: a new outer dict whose
            values are the same objects. Rebinding a key in the copy is independent; mutating a
            shared inner list is not. (Unit 1.7 covers deep copies.)
            """
        ),
        code(
            """
            dosa_recipe = {"ingredients": ["rice", "urad dal"], "price": 60}
            copied_recipe = dosa_recipe.copy()
            unpacked_recipe = {**dosa_recipe, "price": 65}
            copied_recipe["price"] = 70  # rebinding: only the copy changes
            copied_recipe["ingredients"].append("salt")  # mutating a shared list
            print(f"{dosa_recipe=}")
            print(f"{unpacked_recipe=}")
            print(f"{copied_recipe['ingredients'] is dosa_recipe['ingredients']=}")
            """
        ),
        md(
            """
            **Changing size during iteration raises `RuntimeError`.** Adding or deleting keys
            while a `for` loop walks the dict could skip or repeat entries after a resize, so
            CPython detects the size change and stops. Replacing values is allowed. To delete
            while looping, iterate over a snapshot (`list(d)`) or build a new dict.
            """
        ),
        code(
            """
            stock_levels = {"rice": 12, "dal": 0, "ghee": 0, "salt": 7}
            try:
                for item_name in stock_levels:
                    if stock_levels[item_name] == 0:
                        del stock_levels[item_name]
            except RuntimeError as error:
                print(f"{type(error).__name__}: {error}")
            for item_name in stock_levels:
                stock_levels[item_name] += 1  # replacing values is fine
            for item_name in list(stock_levels):  # snapshot of the keys
                if stock_levels[item_name] == 1:
                    del stock_levels[item_name]
            print(f"{stock_levels=}")
            """
        ),
    ]


def _js_comparison_cells() -> list[NotebookNode]:
    """1.6.4 dict vs JS objects."""
    return [
        md(
            """
            ### 1.6.4 dict vs JS objects

            A Python `dict` behaves much more like a JS `Map` than like a plain object.

            | Feature | JS `Object` | JS `Map` | Python `dict` |
            | --- | --- | --- | --- |
            | Key types | strings and symbols only | any value | any **hashable** object (`str`, `int`, `tuple`, `frozenset`, …) |
            | Key coercion | `obj[1]` and `obj["1"]` are the same key | none | none: `1` and `"1"` differ (but `1 == 1.0 == True` collapse, 1.6.2) |
            | Prototype keys | inherited: `"toString" in {}` is `true` | none | none: methods are attributes, never keys |
            | Order | integer-like keys first (ascending), then other strings in insertion order | insertion order | insertion order (guaranteed since 3.7) |
            | Size | `Object.keys(obj).length` | `map.size` | `len(d)` |
            | Missing key | `undefined` | `undefined` | `KeyError` with `d[key]`; `None`/default with `d.get(key)` |
            | Dot access | `obj.name` | no | no: `d["name"]`; use `SimpleNamespace` or a class |
            | JSON | native | needs conversion | `json.dumps(d)` (string keys only; see 1.6.12) |

            The next cell checks the Python column.
            """
        ),
        code(
            """
            mixed_keys = {1: "int one", "1": "string one", (2, 3): "tuple key"}
            print(f"{len(mixed_keys)=}, {mixed_keys[1]=}, {mixed_keys['1']=}")
            empty_dict: dict[str, int] = {}
            print(f"{'keys' in empty_dict=}, {'__init__' in empty_dict=}  (methods are not keys)")
            insertion_ordered = {"b": 1, 10: 2, "a": 3, 2: 4}
            print(f"{list(insertion_ordered)=}  (JS would list 2 and 10 first)")
            print(f"missing key: {raised_error_name(lambda: empty_dict['name'])}")
            """
        ),
        md(
            """
            **`types.SimpleNamespace`** gives JS-style attribute access (`config.port`) over a
            plain `__dict__`. It supports `==`, a readable `repr` and adding attributes later; a
            missing attribute raises `AttributeError`. *New in 3.13:* it also accepts a mapping or
            an iterable of pairs as a positional argument, handy for parsed JSON.
            """
        ),
        code(
            """
            app_config = types.SimpleNamespace(debug=False, port=8000)
            app_config.port = 8080
            app_config.log_level = "INFO"
            print(f"{app_config=}")
            print(f"{app_config.port=}, {vars(app_config)=}")
            print(f"missing attribute: {raised_error_name(lambda: app_config.timeout)}")
            if sys.version_info >= (3, 13):
                parsed_config = types.SimpleNamespace(json.loads('{"host": "localhost"}'), port=5432)
                print(f"{parsed_config=}")
            else:
                print("SimpleNamespace(mapping) needs Python 3.13+; skipped on this kernel")
            """
        ),
    ]


def _immutable_mapping_cells() -> list[NotebookNode]:
    """1.6.5 Immutable mappings."""
    return [
        md(
            """
            ### 1.6.5 Immutable mappings

            **`frozendict`** (*New in 3.15*, PEP 814) is a built-in immutable dict. It is
            hashable when all its values are, so it can be a dict key, a set member or a safe
            module-level constant. It supports the read-only dict API (`[]`, `get`, `keys`,
            `values`, `items`, `copy`, `fromkeys`, `in`, `len`, `==`), and `|` returns a **new**
            `frozendict`. It compares equal to a `dict` with the same pairs.

            The cell is guarded by a version check (convention 5).
            """
        ),
        code(
            '''
            def try_assign(mapping: Any, key: str, value: object) -> None:
                """Run mapping[key] = value (assignment cannot go in a lambda)."""
                mapping[key] = value


            if sys.version_info >= (3, 15):
                GST_RATES = frozendict(food=5, electronics=18, luxury=28)
                print(f"{GST_RATES=}, {GST_RATES['food']=}")
                print(f"item assignment: {raised_error_name(lambda: try_assign(GST_RATES, 'food', 0))}")
                rates_with_services = GST_RATES | {"services": 18}
                print(f"{type(rates_with_services).__name__=}, {len(rates_with_services)=}, {len(GST_RATES)=}")
                rate_table_years = {GST_RATES: "FY2026"}  # hashable, so usable as a key
                print(f"{rate_table_years[frozendict(luxury=28, food=5, electronics=18)]=}")
                print(f"{GST_RATES == {'food': 5, 'electronics': 18, 'luxury': 28}=}")
                print(f"unhashable value: {raised_error_name(lambda: hash(frozendict(tags=['veg'])))}")
            else:
                print("frozendict is new in Python 3.15; this kernel is older, so the demo is skipped")
            '''
        ),
        md(
            """
            **`types.MappingProxyType`** wraps an existing dict in a read-only **live view**: no
            writes through the proxy, but changes to the underlying dict show through. It is how
            CPython exposes class namespaces (`SomeClass.__dict__`), and how a module can hand out
            its settings without letting callers change them. It is not a snapshot and is hashable
            only if the wrapped mapping is (a dict is not).

            | | `dict` | `frozendict` | `MappingProxyType` |
            | --- | --- | --- | --- |
            | Writable | yes | no | no (through the proxy) |
            | Sees later changes | — | no (it owns its data) | yes (a live view) |
            | Hashable | no | yes, if the values are | no (wraps a dict) |
            | Available | always | 3.15+ | 3.3+ |
            """
        ),
        code(
            """
            _settings_store = {"currency": "INR", "tax_rate": 18}
            SETTINGS_VIEW = types.MappingProxyType(_settings_store)
            print(f"{SETTINGS_VIEW['currency']=}")
            write_result = raised_error_name(lambda: try_assign(SETTINGS_VIEW, "currency", "USD"))
            print(f"write through the proxy: {write_result}")
            _settings_store["tax_rate"] = 12
            print(f"{SETTINGS_VIEW['tax_rate']=}  (live: sees the change)")
            print(f"hash(SETTINGS_VIEW): {raised_error_name(lambda: hash(SETTINGS_VIEW))}")
            print(f"{type(int.__dict__).__name__=}  (class namespaces are exposed this way)")
            """
        ),
    ]


def _set_cells() -> list[NotebookNode]:
    """1.6.6 Sets and frozen sets."""
    return [
        md(
            """
            ### 1.6.6 Sets (`set`) and frozen sets (`frozenset`)

            A `set` is a hash table of keys with no values: same hashing rules as dict keys,
            O(1) average `in`, no duplicates, no order guarantee. `{}` is an empty **dict**
            (dicts came first), so an empty set is written `set()`.
            """
        ),
        code(
            """
            empty_braces = {}
            empty_set = set()
            print(f"{type(empty_braces).__name__=}, {type(empty_set).__name__=}")
            visited_cities = {"Pune", "Delhi", "Pune", "Goa"}  # noqa: B033
            print(f"{sorted(visited_cities)=}, {len(visited_cities)=}")
            print(f"{sorted(set('banana'))=}  (a str is an iterable of characters)")
            print(f"list as an element: {raised_error_name(lambda: {['Pune']})}")
            """
        ),
        md(
            """
            **Adding and removing.** `add(x)` adds one element; `update(*iterables)` adds every
            element of each iterable. `remove(x)` raises `KeyError` if `x` is missing, while
            `discard(x)` does nothing. `pop()` removes and returns an **arbitrary** element, so
            the cell does not print which one. `clear()` empties the set.
            """
        ),
        code(
            """
            user_roles = {"viewer"}
            user_roles.add("editor")
            user_roles.add("viewer")  # already present: no change
            user_roles.update(["admin", "auditor"], ("editor",))
            print(f"{sorted(user_roles)=}")
            user_roles.discard("guest")  # absent: silently ignored
            print(f"remove absent: {raised_error_name(lambda: user_roles.remove('guest'))}")
            user_roles.remove("auditor")
            popped_role = user_roles.pop()
            print(f"{popped_role in {'viewer', 'editor', 'admin'}=}, {len(user_roles)=}")
            user_roles.clear()
            print(f"{user_roles=}")
            """
        ),
        md(
            """
            **Operators vs methods.** `|` union, `&` intersection, `-` difference, `^` symmetric
            difference. The named methods do the same, but accept **any iterables**, and several
            at once; the operators require sets (or frozensets) on both sides.
            """
        ),
        code(
            """
            python_developers = {"asha", "ravi", "meena"}
            javascript_developers = {"ravi", "john", "meena"}
            print(f"{sorted(python_developers | javascript_developers)=}")
            print(f"{sorted(python_developers & javascript_developers)=}")
            print(f"{sorted(python_developers - javascript_developers)=}")
            print(f"{sorted(python_developers ^ javascript_developers)=}")
            print(f"{sorted(python_developers.union(['zoe'], ('kim',)))=}")
            print(f"{sorted(python_developers.intersection(['ravi', 'kim']))=}")
            print(f"set | list: {raised_error_name(lambda: python_developers | ['zoe'])}")
            """
        ),
        md(
            """
            **Relations.** `issubset` (`<=`), `issuperset` (`>=`) and `isdisjoint` (no common
            elements). `<` and `>` test *proper* subsets (subset and not equal).
            """
        ),
        code(
            """
            required_permissions = {"read", "write"}
            granted_permissions = {"read", "write", "delete"}
            print(f"{required_permissions.issubset(granted_permissions)=}")
            print(f"{granted_permissions.issuperset(required_permissions)=}")
            print(f"{required_permissions < granted_permissions=}  (proper subset)")
            print(f"{required_permissions < required_permissions=}  (equal is not proper)")
            print(f"{required_permissions.isdisjoint({'admin', 'billing'})=}")
            """
        ),
        md(
            """
            **In-place variants.** `|=`, `&=`, `-=`, `^=` (and the methods `update`,
            `intersection_update`, `difference_update`, `symmetric_difference_update`) change the
            set itself instead of building a new one, so every alias sees the change.
            """
        ),
        code(
            """
            active_users = {"asha", "ravi"}
            same_set_alias = active_users
            active_users |= {"meena"}
            active_users -= {"ravi"}
            active_users &= {"asha", "meena", "john"}
            active_users ^= {"john"}
            print(f"{sorted(active_users)=}, {active_users is same_set_alias=}")
            active_users = active_users | {"kim"}  # plain | rebinds to a new set
            print(f"{active_users is same_set_alias=}")
            """
        ),
        md("**Set comprehensions** use braces with a single expression (no `key: value`)."),
        code(
            """
            raw_emails = ["Asha@Example.com", "ravi@example.com ", "asha@example.com"]
            unique_domains = {email.strip().lower().split("@")[1] for email in raw_emails}
            unique_emails = {email.strip().lower() for email in raw_emails}
            print(f"{unique_domains=}")
            print(f"{sorted(unique_emails)=}")
            """
        ),
        md(
            """
            **`frozenset`** is the immutable, hashable set. Use it where a set must be a dict key
            or a set member: here, an undirected route where `{"Pune", "Mumbai"}` and
            `{"Mumbai", "Pune"}` are the same key.
            """
        ),
        code(
            """
            route_distances_km = {
                frozenset({"Pune", "Mumbai"}): 150,
                frozenset({"Delhi", "Agra"}): 230,
            }
            print(f"{route_distances_km[frozenset({'Mumbai', 'Pune'})]=}  (order does not matter)")
            set_as_key_result = raised_error_name(lambda: {set(["Pune"]): 1})
            print(f"plain set as a key: {set_as_key_result}")
            """
        ),
    ]


def _collections_cells() -> list[NotebookNode]:
    """1.6.7 The collections module."""
    return [
        md(
            """
            ### 1.6.7 The `collections` module

            Five specialised containers. 1.6.11 lists every method again with one demo each.

            #### `deque`: double-ended queue

            A `deque` (say "deck") is a doubly linked list of fixed-size blocks: O(1) appends and
            pops at **both** ends. `extendleft` adds items one at a time to the front, so their
            order flips.
            """
        ),
        code(
            """
            print_queue = deque(["report.pdf"])
            print_queue.append("invoice.pdf")
            print_queue.appendleft("urgent.pdf")
            print(f"{print_queue=}")
            print(f"{print_queue.popleft()=}, {print_queue.pop()=}, {print_queue=}")
            print_queue.extendleft(["b.pdf", "a.pdf"])
            print(f"{print_queue=}  (extendleft reversed the order)")
            """
        ),
        md(
            "`rotate(n)` moves `n` items from the right end to the left (negative `n` goes the other way): a round-robin."
        ),
        code(
            """
            server_pool = deque(["server-a", "server-b", "server-c"])
            server_pool.rotate(1)
            print(f"after rotate(1):  {list(server_pool)}")
            server_pool.rotate(-2)
            print(f"after rotate(-2): {list(server_pool)}")
            """
        ),
        md(
            """
            `maxlen` makes a **ring buffer**: once full, each append drops an item from the other
            end. Ideal for "the last N readings".
            """
        ),
        code(
            """
            recent_temperatures: deque[float] = deque(maxlen=3)
            for reading in [21.5, 22.0, 22.4, 23.1, 22.8]:
                recent_temperatures.append(reading)
                print(f"after {reading}: {list(recent_temperatures)}")
            print(f"{recent_temperatures.maxlen=}")
            """
        ),
        md(
            """
            **Benchmark: `deque.popleft()` vs `list.pop(0)`.** Draining a queue from the front is
            O(n) per pop on a list (every remaining pointer shifts left), so the whole drain is
            O(n²); on a deque it is O(1) per pop. Tripling the size should roughly triple the
            deque time and multiply the list time by about nine (timings vary by machine).
            """
        ),
        code(
            '''
            def drain_list_from_front(item_count: int) -> None:
                """Empty a list by popping index 0."""
                waiting_jobs = list(range(item_count))
                while waiting_jobs:
                    waiting_jobs.pop(0)


            def drain_deque_from_front(item_count: int) -> None:
                """Empty a deque with popleft()."""
                waiting_jobs = deque(range(item_count))
                while waiting_jobs:
                    waiting_jobs.popleft()


            def seconds_for(drain: Callable[[int], None], item_count: int) -> float:
                """Time one call of drain(item_count)."""
                return timeit.timeit(lambda: drain(item_count), number=1)


            for item_count in (10_000, 30_000):
                list_ms = seconds_for(drain_list_from_front, item_count) * 1e3
                deque_ms = seconds_for(drain_deque_from_front, item_count) * 1e3
                print(f"{item_count:>6} items: list.pop(0) {list_ms:8.2f} ms, popleft() {deque_ms:6.2f} ms")
            '''
        ),
        md(
            """
            #### `Counter`: a dict of counts

            `Counter(iterable)` counts hashable items; it is a `dict` subclass mapping item →
            count. `most_common(n)` returns the top `n` pairs (ties keep first-seen order).
            `update` **adds** counts (unlike `dict.update`, which replaces), `subtract` removes
            them (counts may go to zero or below), `total()` sums the counts, and `elements()`
            repeats each item by its count.
            """
        ),
        code(
            """
            dish_orders = ["dosa", "idli", "dosa", "vada", "dosa", "idli"]
            dish_counts = Counter(dish_orders)
            print(f"{dish_counts=}")
            print(f"{dish_counts.most_common(2)=}")
            dish_counts.update(["vada", "vada"])
            dish_counts.update({"dosa": 2})
            dish_counts.subtract({"idli": 3})
            print(f"{dish_counts=}  (idli went negative)")
            print(f"{dish_counts.total()=}")
            print(f"{list(Counter(dosa=2, vada=1).elements())=}")
            """
        ),
        md(
            """
            **Counter arithmetic.** `+` adds, `-` subtracts and **drops** zero and negative counts,
            `&` keeps the minimum of each count, `|` the maximum.
            """
        ),
        code(
            """
            morning_sales = Counter(dosa=5, idli=3, vada=1)
            evening_sales = Counter(dosa=2, vada=4)
            print(f"{morning_sales + evening_sales=}")
            print(f"{morning_sales - evening_sales=}  (vada 1 - 4 dropped)")
            print(f"{morning_sales & evening_sales=}  (minimum)")
            print(f"{morning_sales | evening_sales=}  (maximum)")
            """
        ),
        md(
            """
            #### `defaultdict`: a dict that creates missing values

            `defaultdict(factory)` calls `factory()` to create a value whenever a **missing key is
            read** with `[]`, stores it, and returns it. The factory is any zero-argument
            callable (`list`, `int`, `set`, a lambda) and is stored in `default_factory`. Reading a
            key you did not mean to create still inserts it, which can surprise you.
            """
        ),
        code(
            """
            dishes_by_customer: defaultdict[str, list[str]] = defaultdict(list)
            for customer_name, dish in [("asha", "dosa"), ("ravi", "idli"), ("asha", "vada")]:
                dishes_by_customer[customer_name].append(dish)
            print(f"{dict(dishes_by_customer)=}")
            print(f"{dishes_by_customer.default_factory=}")
            print(f"{dishes_by_customer['zoe']=}  (a read created the key)")
            print(f"{'zoe' in dishes_by_customer=}")
            """
        ),
        md(
            """
            **Nested defaultdicts.** The factory can itself build a defaultdict, giving two-level
            counting without any "does the inner dict exist yet?" checks. A function that returns
            `defaultdict(itself)` gives an auto-vivifying tree of any depth.
            """
        ),
        code(
            '''
            sales_by_city_and_dish: defaultdict[str, defaultdict[str, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            sales_by_city_and_dish["Pune"]["dosa"] += 3
            sales_by_city_and_dish["Pune"]["idli"] += 1
            sales_by_city_and_dish["Goa"]["dosa"] += 2
            print(json.dumps(sales_by_city_and_dish, sort_keys=True))


            def auto_tree() -> defaultdict[str, Any]:
                """Return a defaultdict whose missing values are more auto_trees."""
                return defaultdict(auto_tree)


            site_map = auto_tree()
            site_map["shop"]["cart"]["checkout"] = "checkout.html"
            print(json.dumps(site_map))
            '''
        ),
        md(
            """
            **The `__missing__` hook.** `dict.__getitem__` calls `self.__missing__(key)` when a
            key is absent, if the subclass defines it; `defaultdict` is just a dict with a
            `__missing__` that calls the factory and stores the result. Writing your own lets you
            choose: this one returns `0` **without** inserting. `get()` and `in` never call
            `__missing__`.
            """
        ),
        code(
            '''
            class ZeroDefaultDict(dict[str, int]):
                """A dict that answers 0 for missing keys without storing them."""

                def __missing__(self, key: str) -> int:
                    print(f"  __missing__({key!r}) called")
                    return 0


            stock_counts = ZeroDefaultDict(rice=5)
            print(f"{stock_counts['rice']=}")
            print(f"{stock_counts['ghee']=}")
            print(f"{stock_counts.get('ghee')=}  (get does not call __missing__)")
            print(f"{'ghee' in stock_counts=}  (nothing was inserted)")
            '''
        ),
        md(
            """
            #### `OrderedDict`: order you can rearrange

            Plain dicts have kept insertion order since 3.7, so `OrderedDict` is now for the
            things a dict cannot do: `move_to_end(key, last=True)` (or to the front with
            `last=False`), `popitem(last=False)` to remove the **oldest** item, and **order-sensitive**
            equality between two `OrderedDict`s. That makes it the classic base for an LRU cache
            (Lab 1.6).
            """
        ),
        code(
            """
            recently_viewed = OrderedDict.fromkeys(["home", "cart", "checkout"])
            recently_viewed.move_to_end("home")
            print(f"{list(recently_viewed)=}")
            recently_viewed.move_to_end("checkout", last=False)
            print(f"{list(recently_viewed)=}")
            print(f"{recently_viewed.popitem(last=False)=}  (oldest first)")
            print(f"{OrderedDict(a=1, b=2) == OrderedDict(b=2, a=1)=}")
            print(f"{dict(a=1, b=2) == dict(b=2, a=1)=}")
            print(f"{OrderedDict(a=1, b=2) == {'b': 2, 'a': 1}=}  (vs a dict: order ignored)")
            """
        ),
        md(
            """
            #### `ChainMap`: layered lookups

            `ChainMap(first, second, ...)` searches several mappings in order without copying
            them; the first mapping that has the key wins. Typical use: configuration layers such
            as command line > environment > defaults. Writes and deletes affect only the first
            mapping.
            """
        ),
        code(
            """
            default_settings = {"host": "localhost", "port": 8000, "debug": False}
            environment_settings = {"port": 9000}
            command_line_settings = {"debug": True}
            effective_settings = ChainMap(command_line_settings, environment_settings, default_settings)
            print(f"{effective_settings['port']=}, {effective_settings['debug']=}")
            print(f"{effective_settings['host']=}  (only the defaults have it)")
            print(f"{dict(effective_settings)=}")
            effective_settings["port"] = 7000
            print(f"{command_line_settings=}, {environment_settings=}")
            """
        ),
    ]


def _choosing_cells() -> list[NotebookNode]:
    """1.6.8 Choosing a container."""
    return [
        md(
            """
            ### 1.6.8 Choosing a container

            | Container | Ordered | Mutable | Duplicates | Hashable | Lookup | Reach for it when |
            | --- | --- | --- | --- | --- | --- | --- |
            | `list` | yes | yes | yes | no | by index O(1), by value O(n) | an ordered, growing sequence |
            | `tuple` | yes | no | yes | if items are | by index O(1) | a fixed record or a composite key |
            | `NamedTuple` | yes | no | yes | if fields are | by name or index | a small immutable record with field names |
            | `dict` | insertion | yes | unique keys | no | by key O(1) | mapping keys to values |
            | `set` | no | yes | no | no | `in` O(1) | membership, deduplication, set algebra |
            | `frozenset` | no | no | no | yes | `in` O(1) | a set used as a key or set member |
            | `deque` | yes | yes | yes | no | ends O(1), middle O(n) | queues, sliding windows, last N items |
            | `Counter` | insertion | yes | counts | no | by key O(1) | counting and tallies |
            | `defaultdict` | insertion | yes | unique keys | no | by key O(1) | grouping, building nested data |
            | `frozendict` | insertion | no | unique keys | if values are | by key O(1) | constant lookup tables, mapping-valued keys (3.15+) |
            | `array.array` | yes | yes | yes | no | by index O(1) | large homogeneous numeric data in compact memory |

            #### Under the hood: shallow sizes of the same 1 000 ints

            `sys.getsizeof` counts the container only (pointer arrays, hash tables), not the
            `int` objects, except for `array`, which stores raw machine values. Sizes vary by
            version and platform.
            """
        ),
        code(
            """
            sample_numbers = list(range(1000))
            same_numbers_in = {
                "list": sample_numbers,
                "tuple": tuple(sample_numbers),
                "set": set(sample_numbers),
                "frozenset": frozenset(sample_numbers),
                "dict (value None)": dict.fromkeys(sample_numbers),
                "deque": deque(sample_numbers),
                "array('q')": array.array("q", sample_numbers),
            }
            for container_name, container in same_numbers_in.items():
                print(f"{container_name:<18}{sys.getsizeof(container):>8,} bytes")
            """
        ),
    ]


def _dict_reference_cells() -> list[NotebookNode]:
    """1.6.9 Method reference — dict: one demo cell per table row."""
    return [
        md(
            r"""
            ### 1.6.9 Method reference — `dict`

            Average costs; every row gets a demo cell below.

            | Method / operation | What it does | Returns | Cost |
            | --- | --- | --- | --- |
            | `d[key]` | read a value (`KeyError` if missing) | value | O(1) |
            | `d[key] = value` | insert or replace | — | O(1) |
            | `del d[key]` | delete (`KeyError` if missing) | — | O(1) |
            | `key in d`, `len(d)`, `iter(d)` | membership on keys, size, iterate keys | `bool` / `int` / iterator | O(1) / O(1) / O(n) |
            | `get(key, default=None)` | read without raising | value or default | O(1) |
            | `setdefault(key, default=None)` | read, inserting `default` first if missing | value | O(1) |
            | `pop(key[, default])` | remove and return (`KeyError` without default) | value | O(1) |
            | `popitem()` | remove and return the last inserted pair | `(key, value)` | O(1) |
            | `update(other=(), **kwargs)` | merge a mapping, pairs or keywords in place | `None` | O(k) |
            | `d1 \| d2`, `d1 \|= d2` | merge into a new dict / in place (right wins) | new `dict` / same | O(n + m) |
            | `keys()`, `values()`, `items()` | live views (keys/items support `&`, `\|`, `-`, `^`) | view | O(1) |
            | `copy()` | shallow copy | new `dict` | O(n) |
            | `clear()` | remove everything | `None` | O(n) |
            | `dict.fromkeys(iterable, value=None)` | new dict, every key → the **same** value object | new `dict` | O(n) |
            | `reversed(d)` | iterate keys newest-first | iterator | O(n) |
            | `==` | equal if same key/value pairs (order ignored) | `bool` | O(n) |
            """
        ),
        md(
            """
            #### `dict`

            **`d[key]`**: read a value; a missing key raises `KeyError`.
            """
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40}
            print(f"{price_list['dosa']=}")
            print(f"missing key: {raised_error_name(lambda: price_list['vada'])}")
            """
        ),
        md("**`d[key] = value`**: insert a new key or replace the value of an existing one."),
        code(
            """
            price_list = {"dosa": 60}
            price_list["idli"] = 40  # insert
            price_list["dosa"] = 65  # replace, position unchanged
            print(f"{price_list=}")
            """
        ),
        md(
            "**`del d[key]`**: delete a key; `KeyError` if it is missing (`delete_key` is from 1.6.3)."
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40}
            del price_list["idli"]
            print(f"{price_list=}")
            print(f"del missing: {raised_error_name(lambda: delete_key(price_list, 'idli'))}")
            """
        ),
        md(
            "**`key in d`, `len(d)`, `iter(d)`**: membership tests keys; iterating a dict yields its keys in insertion order."
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40, "vada": 30}
            print(f"{'idli' in price_list=}, {40 in price_list=}, {len(price_list)=}")
            key_iterator = iter(price_list)
            print(f"{next(key_iterator)=}, {list(key_iterator)=}")
            """
        ),
        md("**`get(key, default=None)`**: read without raising."),
        code(
            """
            price_list = {"dosa": 60}
            print(f"{price_list.get('dosa')=}, {price_list.get('vada')=}, {price_list.get('vada', 0)=}")
            """
        ),
        md(
            "**`setdefault(key, default=None)`**: return the value, inserting `default` first if the key is missing."
        ),
        code(
            """
            price_list = {"dosa": 60}
            print(f"{price_list.setdefault('dosa', 99)=}, {price_list.setdefault('vada', 30)=}")
            print(f"{price_list.setdefault('upma')=}, {price_list=}")
            """
        ),
        md(
            "**`pop(key[, default])`**: remove and return a value; without a default a missing key raises `KeyError`."
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40}
            print(f"{price_list.pop('idli')=}, {price_list.pop('idli', None)=}, {price_list=}")
            print(f"pop missing, no default: {raised_error_name(lambda: price_list.pop('idli'))}")
            """
        ),
        md(
            "**`popitem()`**: remove and return the most recently inserted pair (LIFO); `KeyError` when empty."
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40, "vada": 30}
            print(f"{price_list.popitem()=}, {price_list.popitem()=}, {price_list=}")
            print(f"popitem on empty: {raised_error_name({}.popitem)}")
            """
        ),
        md(
            "**`update(other=(), **kwargs)`**: merge in place from a mapping, an iterable of pairs and/or keywords; returns `None`."
        ),
        code(
            """
            price_list = {"dosa": 60}
            update_result = price_list.update({"idli": 40}, vada=30)
            price_list.update([("upma", 45)])
            print(f"{price_list=}, {update_result=}")
            """
        ),
        md(
            r"**`d1 | d2`, `d1 |= d2`**: merge into a new dict, or into `d1` in place; the right side wins on shared keys."
        ),
        code(
            """
            base_prices = {"dosa": 60, "idli": 40}
            festival_prices = {"dosa": 50}
            merged_prices = base_prices | festival_prices
            print(f"{merged_prices=}, {base_prices=}")
            prices_alias = base_prices
            base_prices |= festival_prices
            print(f"{base_prices=}, {base_prices is prices_alias=}")
            """
        ),
        md(
            r"**`keys()`, `values()`, `items()`**: live views; key and item views support `&`, `|`, `-`, `^`."
        ),
        code(
            """
            price_list = {"dosa": 60, "idli": 40}
            price_items = price_list.items()
            price_list["vada"] = 30
            print(f"{price_items=}  (includes vada: the view is live)")
            print(f"{list(price_list.values())=}")
            print(f"{sorted(price_list.keys() - {'idli'})=}, {price_items & {('vada', 30)}=}")
            """
        ),
        md("**`copy()`**: a shallow copy, a new dict holding the same value objects."),
        code(
            """
            price_list = {"dosa": 60, "combo": ["dosa", "chai"]}
            price_copy = price_list.copy()
            price_copy["dosa"] = 70
            print(f"{price_list['dosa']=}, {price_copy['dosa']=}")
            print(f"{price_copy['combo'] is price_list['combo']=}  (shallow)")
            """
        ),
        md("**`clear()`**: remove every item in place; aliases see the empty dict."),
        code(
            """
            price_list = {"dosa": 60, "idli": 40}
            price_alias = price_list
            print(f"{price_list.clear()=}, {price_alias=}")
            """
        ),
        md(
            "**`dict.fromkeys(iterable, value=None)`**: a new dict where every key maps to the **same** value object."
        ),
        code(
            """
            stock_flags = dict.fromkeys(["dosa", "idli", "vada"], False)
            shared_lists = dict.fromkeys(["T1", "T2"], [])
            print(f"{stock_flags=}")
            print(f"{shared_lists['T1'] is shared_lists['T2']=}  (one list, see 1.6.3)")
            """
        ),
        md("**`reversed(d)`**: iterate keys newest-first (since 3.8); works on the views too."),
        code(
            """
            price_list = {"dosa": 60, "idli": 40, "vada": 30}
            print(f"{list(reversed(price_list))=}")
            print(f"{list(reversed(price_list.items()))=}")
            """
        ),
        md("**`==`**: dicts are equal when they hold the same key/value pairs; order is ignored."),
        code(
            """
            print(f"{ {'dosa': 60, 'idli': 40} == {'idli': 40, 'dosa': 60}=}")
            print(f"{ {'dosa': 60} == {'dosa': 60.0}=}  (60 == 60.0)")
            print(f"{ {'dosa': 60} == {'dosa': 65}=}")
            """
        ),
    ]


def _set_reference_cells() -> list[NotebookNode]:
    """1.6.10 Method reference — set and frozenset: one demo cell per table row."""
    return [
        md(
            r"""
            ### 1.6.10 Method reference — `set` and `frozenset`

            | Method | Operator | What it does | Mutates? |
            | --- | --- | --- | --- |
            | `add(x)` | — | add one element | yes |
            | `remove(x)` / `discard(x)` | — | delete (`remove` raises `KeyError`, `discard` does not) | yes |
            | `pop()` | — | remove and return an arbitrary element | yes |
            | `clear()`, `copy()` | — | empty / shallow copy | yes / no |
            | `union(*others)` | `a \| b` | elements in either | no |
            | `intersection(*others)` | `a & b` | elements in both | no |
            | `difference(*others)` | `a - b` | elements only in `a` | no |
            | `symmetric_difference(other)` | `a ^ b` | elements in exactly one | no |
            | `update`, `intersection_update`, `difference_update`, `symmetric_difference_update` | `\|=`, `&=`, `-=`, `^=` | in-place versions | yes |
            | `issubset(other)` / `issuperset(other)` | `<=` / `>=` (`<`, `>` proper) | subset tests | no |
            | `isdisjoint(other)` | — | no common elements | no |

            Methods accept any iterable; operators require sets on both sides. `frozenset` has only the non-mutating methods and is hashable. `x in s` is O(1) on average.

            The demos use small integer ticket numbers: small ints hash to themselves, so these
            sets print in the same order on every run.

            #### `set`

            **`add(x)`**: add one element; adding an existing element changes nothing.
            """
        ),
        code(
            """
            open_tickets = {101, 102}
            open_tickets.add(103)
            open_tickets.add(101)
            print(f"{open_tickets=}")
            """
        ),
        md(
            "**`remove(x)` / `discard(x)`**: delete an element; `remove` raises `KeyError` if it is missing, `discard` does not."
        ),
        code(
            """
            open_tickets = {101, 102, 103}
            open_tickets.remove(101)
            open_tickets.discard(999)
            print(f"{open_tickets=}")
            print(f"remove missing: {raised_error_name(lambda: open_tickets.remove(999))}")
            """
        ),
        md(
            "**`pop()`**: remove and return an arbitrary element (`KeyError` on an empty set). Do not rely on which one."
        ),
        code(
            """
            open_tickets = {101, 102, 103}
            closed_ticket = open_tickets.pop()
            print(f"{closed_ticket in {101, 102, 103}=}, {len(open_tickets)=}")
            print(f"pop on empty: {raised_error_name(set().pop)}")
            """
        ),
        md("**`clear()`, `copy()`**: empty the set in place / make a shallow copy."),
        code(
            """
            open_tickets = {101, 102}
            ticket_snapshot = open_tickets.copy()
            open_tickets.clear()
            print(f"{open_tickets=}, {ticket_snapshot=}")
            """
        ),
        md(r"**`union(*others)` / `a | b`**: elements in either."),
        code(
            """
            team_a_tickets = {101, 102, 103}
            team_b_tickets = {103, 104}
            print(f"{team_a_tickets | team_b_tickets=}")
            print(f"{team_a_tickets.union(team_b_tickets, [105])=}")
            """
        ),
        md("**`intersection(*others)` / `a & b`**: elements in both."),
        code(
            """
            team_a_tickets = {101, 102, 103}
            team_b_tickets = {103, 104, 101}
            print(f"{team_a_tickets & team_b_tickets=}")
            print(f"{team_a_tickets.intersection(team_b_tickets, [101, 999])=}")
            """
        ),
        md("**`difference(*others)` / `a - b`**: elements only in `a`."),
        code(
            """
            team_a_tickets = {101, 102, 103}
            team_b_tickets = {103, 104}
            print(f"{team_a_tickets - team_b_tickets=}")
            print(f"{team_a_tickets.difference(team_b_tickets, [102])=}")
            """
        ),
        md("**`symmetric_difference(other)` / `a ^ b`**: elements in exactly one of the two."),
        code(
            """
            team_a_tickets = {101, 102, 103}
            team_b_tickets = {103, 104}
            print(f"{team_a_tickets ^ team_b_tickets=}")
            print(f"{team_a_tickets.symmetric_difference([103, 104])=}")
            """
        ),
        md(
            r"**`update`, `intersection_update`, `difference_update`, `symmetric_difference_update` / `|=`, `&=`, `-=`, `^=`**: the in-place versions; they return `None` and change the set itself."
        ),
        code(
            """
            ticket_queue = {101, 102}
            ticket_queue.update([103, 104])  # |=
            print(f"after update:                      {ticket_queue}")
            ticket_queue.intersection_update({102, 103, 104, 105})  # &=
            print(f"after intersection_update:         {ticket_queue}")
            ticket_queue.difference_update([104])  # -=
            print(f"after difference_update:           {ticket_queue}")
            ticket_queue.symmetric_difference_update({103, 106})  # ^=
            print(f"after symmetric_difference_update: {ticket_queue}")
            ticket_queue |= {110}
            ticket_queue &= {102, 106, 110}
            ticket_queue -= {106}
            ticket_queue ^= {111}
            print(f"after |= &= -= ^=:                 {ticket_queue}")
            """
        ),
        md(
            "**`issubset(other)` / `issuperset(other)`, `<=` / `>=`, `<` / `>`**: subset tests; `<` and `>` require a *proper* subset or superset."
        ),
        code(
            """
            urgent_tickets = {101, 103}
            open_tickets = {101, 102, 103}
            print(f"{urgent_tickets.issubset(open_tickets)=}, {urgent_tickets <= open_tickets=}")
            print(f"{open_tickets.issuperset([101])=}, {open_tickets >= urgent_tickets=}")
            print(f"{urgent_tickets < open_tickets=}, {open_tickets < open_tickets=}")
            print(f"{open_tickets > urgent_tickets=}")
            """
        ),
        md("**`isdisjoint(other)`**: `True` when the two share no element."),
        code(
            """
            open_tickets = {101, 102}
            print(f"{open_tickets.isdisjoint({201, 202})=}, {open_tickets.isdisjoint([102, 300])=}")
            """
        ),
        md(
            """
            #### `frozenset`

            The notes under the table, one demo each. **Methods accept any iterable; operators
            require sets on both sides** (a `set` and a `frozenset` mix freely; the result takes
            the type of the left operand).
            """
        ),
        code(
            """
            open_tickets = {101, 102}
            print(f"{open_tickets.union(range(103, 105))=}")
            print(f"set | range: {raised_error_name(lambda: open_tickets | range(103, 105))}")
            print(f"{type(frozenset({1}) | {2}).__name__=}, {type({2} | frozenset({1})).__name__=}")
            """
        ),
        md(
            """
            **`frozenset` has only the non-mutating methods and is hashable.** Mutators such as
            `add` do not exist on it; it can be a dict key or an element of another set.
            """
        ),
        code(
            """
            weekend_days = frozenset({"sat", "sun"})
            print(f"{hasattr(weekend_days, 'add')=}, {hasattr(weekend_days, 'union')=}")
            print(f"add: {raised_error_name(lambda: weekend_days.add('fri'))}")
            print(f"{sorted(weekend_days | {'fri'})=}  (returns a new frozenset)")
            schedules = {weekend_days: "relaxed", frozenset({"mon"}): "busy"}
            print(f"{schedules[frozenset({'sun', 'sat'})]=}")
            set_of_sets = {frozenset({1, 2}), frozenset({2, 1}), frozenset({3})}
            print(f"{len(set_of_sets)=}")
            """
        ),
        md(
            """
            **`x in s` is O(1) on average**: a hash and a probe, independent of the set size.
            A list scans every element. Timings vary by machine.
            """
        ),
        code(
            """
            ticket_numbers = list(range(100_000))
            ticket_set = frozenset(ticket_numbers)
            list_seconds = timeit.timeit(lambda: -1 in ticket_numbers, number=50)
            set_seconds = timeit.timeit(lambda: -1 in ticket_set, number=50)
            print(f"list: {list_seconds / 50 * 1e6:9.2f} µs per lookup")
            print(f"set:  {set_seconds / 50 * 1e6:9.3f} µs per lookup")
            """
        ),
    ]


def _collections_reference_cells() -> list[NotebookNode]:
    """1.6.11 Method reference — collections: a heading per type, a demo per named API."""
    return [
        md(
            r"""
            ### 1.6.11 Method reference — `collections`

            | Type | Key methods and attributes |
            | --- | --- |
            | `deque` | `append`, `appendleft`, `pop`, `popleft`, `extend`, `extendleft`, `rotate(n)`, `insert`, `remove`, `count`, `index`, `reverse`, `clear`, `copy`, `maxlen` |
            | `Counter` | `most_common(n)`, `elements()`, `update`, `subtract`, `total()`, `+ - & \|`; missing keys count as 0 |
            | `defaultdict` | `default_factory`, the `__missing__` hook; all `dict` methods |
            | `OrderedDict` | `move_to_end(key, last=True)`, `popitem(last=True)`, order-sensitive `==` |
            | `ChainMap` | `maps`, `new_child()`, `parents`; writes go to the first mapping |
            | `namedtuple` | see 1.5.10 |

            Each row lists several APIs, so each API gets its own short demo below.

            #### `deque`

            **`append(x)`**: add to the right end, O(1).
            """
        ),
        code(
            """
            call_queue = deque(["caller-1"])
            call_queue.append("caller-2")
            print(f"{call_queue=}")
            """
        ),
        md("**`appendleft(x)`**: add to the left end, O(1)."),
        code(
            """
            call_queue = deque(["caller-1"])
            call_queue.appendleft("vip-caller")
            print(f"{call_queue=}")
            """
        ),
        md("**`pop()`**: remove and return from the right end; `IndexError` when empty."),
        code(
            """
            call_queue = deque(["caller-1", "caller-2"])
            print(f"{call_queue.pop()=}, {call_queue=}")
            print(f"pop on empty: {raised_error_name(deque().pop)}")
            """
        ),
        md("**`popleft()`**: remove and return from the left end, O(1); `IndexError` when empty."),
        code(
            """
            call_queue = deque(["caller-1", "caller-2"])
            print(f"{call_queue.popleft()=}, {call_queue=}")
            print(f"popleft on empty: {raised_error_name(deque().popleft)}")
            """
        ),
        md("**`extend(iterable)`**: append every item on the right, in order."),
        code(
            """
            call_queue = deque(["caller-1"])
            call_queue.extend(["caller-2", "caller-3"])
            print(f"{call_queue=}")
            """
        ),
        md(
            "**`extendleft(iterable)`**: appendleft every item, one at a time, so they end up reversed."
        ),
        code(
            """
            call_queue = deque(["caller-3"])
            call_queue.extendleft(["caller-2", "caller-1"])
            print(f"{call_queue=}")
            """
        ),
        md("**`rotate(n)`**: rotate `n` steps right (negative `n`: left)."),
        code(
            """
            shift_rota = deque(["asha", "ravi", "meena", "john"])
            shift_rota.rotate(1)
            print(f"{shift_rota=}")
            shift_rota.rotate(-1)
            print(f"{shift_rota=}")
            """
        ),
        md(
            "**`insert(i, x)`**: insert before index `i` (O(n) towards the middle); `IndexError` on a full bounded deque."
        ),
        code(
            """
            call_queue = deque(["caller-1", "caller-3"])
            call_queue.insert(1, "caller-2")
            print(f"{call_queue=}")
            bounded_queue = deque([1, 2], maxlen=2)
            print(f"insert into full deque: {raised_error_name(lambda: bounded_queue.insert(0, 0))}")
            """
        ),
        md("**`remove(x)`**: delete the first item equal to `x`; `ValueError` if absent."),
        code(
            """
            call_queue = deque(["caller-1", "spam", "caller-2", "spam"])
            call_queue.remove("spam")
            print(f"{call_queue=}")
            print(f"remove missing: {raised_error_name(lambda: call_queue.remove('nobody'))}")
            """
        ),
        md("**`count(x)`**: how many items equal `x`."),
        code(
            """
            call_queue = deque(["asha", "ravi", "asha"])
            print(f"{call_queue.count('asha')=}, {call_queue.count('zoe')=}")
            """
        ),
        md("**`index(x[, start[, stop]])`**: position of the first `x`; `ValueError` if absent."),
        code(
            """
            call_queue = deque(["asha", "ravi", "asha"])
            print(f"{call_queue.index('asha')=}, {call_queue.index('asha', 1)=}")
            print(f"index missing: {raised_error_name(lambda: call_queue.index('zoe'))}")
            """
        ),
        md("**`reverse()`**: reverse in place; returns `None`."),
        code(
            """
            call_queue = deque([1, 2, 3])
            print(f"{call_queue.reverse()=}, {call_queue=}")
            """
        ),
        md("**`clear()`**: remove every item."),
        code(
            """
            call_queue = deque([1, 2, 3])
            call_queue.clear()
            print(f"{call_queue=}, {len(call_queue)=}")
            """
        ),
        md("**`copy()`**: shallow copy that keeps `maxlen`."),
        code(
            """
            recent_calls = deque(["asha", "ravi"], maxlen=3)
            calls_copy = recent_calls.copy()
            calls_copy.append("meena")
            print(f"{recent_calls=}, {calls_copy=}")
            """
        ),
        md(
            "**`maxlen`**: read-only bound (`None` if unbounded); a full deque drops items from the opposite end."
        ),
        code(
            """
            recent_calls = deque(maxlen=2)
            recent_calls.extend(["asha", "ravi", "meena"])
            recent_calls.appendleft("john")  # drops from the right
            print(f"{recent_calls=}, {recent_calls.maxlen=}, {deque().maxlen=}")
            """
        ),
        md(
            """
            #### `Counter`

            **`most_common(n)`**: the `n` largest counts as `(item, count)` pairs; ties keep first-seen order. No argument returns all.
            """
        ),
        code(
            """
            page_views = Counter(["/home", "/cart", "/home", "/pay", "/cart", "/home"])
            print(f"{page_views.most_common(2)=}")
            print(f"{page_views.most_common()=}")
            """
        ),
        md(
            "**`elements()`**: an iterator repeating each item by its count (items with count ≤ 0 are skipped)."
        ),
        code(
            """
            ingredient_counts = Counter(egg=2, flour=1, salt=0)
            print(f"{list(ingredient_counts.elements())=}")
            """
        ),
        md("**`update(iterable_or_mapping)`**: **add** counts (`dict.update` would replace them)."),
        code(
            """
            page_views = Counter({"/home": 3})
            page_views.update(["/home", "/cart"])
            page_views.update({"/cart": 5})
            print(f"{page_views=}")
            """
        ),
        md(
            "**`subtract(iterable_or_mapping)`**: subtract counts in place; results may be zero or negative."
        ),
        code(
            """
            warehouse_stock = Counter(soap=5, tea=2)
            warehouse_stock.subtract({"tea": 3, "soap": 1})
            print(f"{warehouse_stock=}")
            """
        ),
        md("**`total()`**: the sum of all counts (since 3.10)."),
        code(
            """
            page_views = Counter({"/home": 3, "/cart": 2})
            print(f"{page_views.total()=}, {sum(page_views.values())=}")
            """
        ),
        md(
            r"**`+ - & |`**: add, subtract (dropping counts ≤ 0), minimum, maximum. Unary `+c` drops non-positive counts too."
        ),
        code(
            """
            shop_a = Counter(soap=3, tea=1)
            shop_b = Counter(soap=1, tea=4, rice=2)
            print(f"{shop_a + shop_b=}")
            print(f"{shop_a - shop_b=}")
            print(f"{shop_a & shop_b=}, {shop_a | shop_b=}")
            print(f"{+Counter(soap=2, tea=-1, rice=0)=}")
            """
        ),
        md(
            "**Missing keys count as 0**: reading one returns `0` and does **not** insert it (unlike `defaultdict`)."
        ),
        code(
            """
            page_views = Counter({"/home": 3})
            print(f"{page_views['/missing']=}, {'/missing' in page_views=}")
            page_views["/new"] += 1
            print(f"{page_views=}")
            """
        ),
        md(
            """
            #### `defaultdict`

            **`default_factory`**: the zero-argument callable used for missing keys; it can be
            changed later, and `None` turns the defaultdict back into plain-dict behaviour.
            """
        ),
        code(
            """
            tickets_by_agent = defaultdict(set)
            tickets_by_agent["asha"].add(101)
            print(f"{tickets_by_agent.default_factory=}, {dict(tickets_by_agent)=}")
            tickets_by_agent.default_factory = None
            print(f"missing key, factory None: {raised_error_name(lambda: tickets_by_agent['ravi'])}")
            """
        ),
        md(
            "**The `__missing__` hook**: `defaultdict.__missing__(key)` calls the factory, stores the value and returns it; `d[key]` calls it on a miss."
        ),
        code(
            """
            page_counts = defaultdict(int)
            print(f"{page_counts.__missing__('/home')=}, {dict(page_counts)=}")
            page_counts["/cart"] += 1  # __getitem__ miss → __missing__ → 0, then += 1
            print(f"{dict(page_counts)=}")
            """
        ),
        md(
            "**All `dict` methods**: it *is* a dict subclass. `get`, `in` and `setdefault` do not call the factory."
        ),
        code(
            """
            page_counts = defaultdict(int, {"/home": 3})
            print(f"{isinstance(page_counts, dict)=}")
            print(f"{page_counts.get('/cart')=}, {'/cart' in page_counts=}  (no insert)")
            page_counts.update({"/pay": 1})
            print(f"{sorted(page_counts.items())=}, {page_counts.pop('/pay')=}")
            """
        ),
        md(
            """
            #### `OrderedDict`

            **`move_to_end(key, last=True)`**: move a key to the end, or to the front with
            `last=False`; `KeyError` if it is missing.
            """
        ),
        code(
            """
            browser_tabs = OrderedDict.fromkeys(["mail", "docs", "news"])
            browser_tabs.move_to_end("mail")
            print(f"{list(browser_tabs)=}")
            browser_tabs.move_to_end("news", last=False)
            print(f"{list(browser_tabs)=}")
            print(f"missing key: {raised_error_name(lambda: browser_tabs.move_to_end('chat'))}")
            """
        ),
        md("**`popitem(last=True)`**: remove the newest pair, or the oldest with `last=False`."),
        code(
            """
            browser_tabs = OrderedDict(mail=1, docs=2, news=3)
            print(f"{browser_tabs.popitem()=}, {browser_tabs.popitem(last=False)=}, {browser_tabs=}")
            """
        ),
        md(
            "**Order-sensitive `==`**: between two `OrderedDict`s order matters; against a plain `dict` it does not."
        ),
        code(
            """
            first_order = OrderedDict(mail=1, docs=2)
            second_order = OrderedDict(docs=2, mail=1)
            print(f"{first_order == second_order=}, {first_order == dict(second_order)=}")
            """
        ),
        md(
            """
            #### `ChainMap`

            **`maps`**: the list of underlying mappings, searched front to back; it can be edited.
            """
        ),
        code(
            """
            built_in_defaults = {"theme": "light", "font_size": 14}
            user_overrides = {"theme": "dark"}
            layered_settings = ChainMap(user_overrides, built_in_defaults)
            print(f"{layered_settings.maps=}")
            print(f"{layered_settings['theme']=}, {layered_settings['font_size']=}")
            """
        ),
        md(
            "**`new_child(m=None)`**: a new ChainMap with an extra (empty or given) mapping in front, the others unchanged; handy for nested scopes."
        ),
        code(
            """
            built_in_defaults = {"theme": "light", "font_size": 14}
            layered_settings = ChainMap(built_in_defaults)
            session_settings = layered_settings.new_child({"font_size": 18})
            print(f"{session_settings['font_size']=}, {layered_settings['font_size']=}")
            print(f"{len(session_settings.maps)=}")
            """
        ),
        md(
            "**`parents`**: a ChainMap of every mapping except the first (skip the innermost scope)."
        ),
        code(
            """
            scope_chain = ChainMap({"x": "local"}, {"x": "enclosing"}, {"x": "global"})
            print(f"{scope_chain['x']=}, {scope_chain.parents['x']=}")
            print(f"{scope_chain.parents.parents['x']=}")
            """
        ),
        md("**Writes go to the first mapping**: assignment, `del` and `pop` touch only `maps[0]`."),
        code(
            """
            built_in_defaults = {"theme": "light"}
            user_overrides: dict[str, str] = {}
            layered_settings = ChainMap(user_overrides, built_in_defaults)
            layered_settings["theme"] = "dark"
            print(f"{user_overrides=}, {built_in_defaults=}")
            del layered_settings["theme"]
            print(f"{layered_settings['theme']=}  (the default shows through again)")
            print(f"del a key only in a later map: {raised_error_name(lambda: layered_settings.pop('theme'))}")
            """
        ),
        md(
            """
            #### `namedtuple`

            Covered in 1.5.6 and 1.5.10 (`_fields`, `_make`, `_asdict`, `_replace`, defaults).
            One reminder cell:
            """
        ),
        code(
            """
            Coordinates = namedtuple("Coordinates", ["latitude", "longitude"])
            office_location = Coordinates(18.52, 73.86)
            print(f"{Coordinates._fields=}, {office_location._replace(longitude=73.9)=}")
            """
        ),
    ]


def _pattern_cells() -> list[NotebookNode]:
    """1.6.12 Common dictionary patterns."""
    return [
        md(
            """
            ### 1.6.12 Common dictionary patterns

            Ten patterns you will write every week. The first two reuse `LogEntry` from 1.5.6
            (re-defined in this unit's setup), which the Phase 1 project builds on.

            **Counting.** The manual `get(key, 0) + 1` loop and `Counter` give the same counts;
            `Counter` also gives `most_common`.
            """
        ),
        code(
            """
            access_log = [
                LogEntry("INFO", "GET /home"),
                LogEntry("ERROR", "db timeout", 500),
                LogEntry("INFO", "GET /cart"),
                LogEntry("WARNING", "slow query"),
                LogEntry("ERROR", "gateway timeout", 504),
                LogEntry("INFO", "GET /pay"),
            ]
            level_counts_manual: dict[str, int] = {}
            for log_entry in access_log:
                level_counts_manual[log_entry.level] = level_counts_manual.get(log_entry.level, 0) + 1
            level_counts = Counter(log_entry.level for log_entry in access_log)
            print(f"{level_counts_manual=}")
            print(f"{level_counts.most_common(1)=}, {level_counts_manual == level_counts=}")
            """
        ),
        md(
            """
            **Grouping.** `defaultdict(list)` and `setdefault(key, []).append(...)` both collect
            items per key. Convert a defaultdict to a plain `dict` before returning it, so later
            reads of missing keys raise instead of inserting.
            """
        ),
        code(
            """
            messages_by_level: defaultdict[str, list[str]] = defaultdict(list)
            for log_entry in access_log:
                messages_by_level[log_entry.level].append(log_entry.message)
            status_codes_by_level: dict[str, list[int]] = {}
            for log_entry in access_log:
                status_codes_by_level.setdefault(log_entry.level, []).append(log_entry.status_code)
            print(f"{dict(messages_by_level)=}")
            print(f"{status_codes_by_level=}")
            """
        ),
        md(
            """
            **Indexing records by ID.** One comprehension turns a list of rows into an O(1)
            lookup. If two rows share an ID, the last one silently wins, so check the length.
            """
        ),
        code(
            """
            customer_rows = [
                {"id": 7, "name": "Asha", "city": "Pune"},
                {"id": 3, "name": "Ravi", "city": "Goa"},
                {"id": 9, "name": "Meena", "city": "Pune"},
            ]
            customers_by_id = {row["id"]: row for row in customer_rows}
            print(f"{customers_by_id[3]['name']=}, {sorted(customers_by_id)=}")
            print(f"{len(customers_by_id) == len(customer_rows)=}  (no duplicate IDs)")
            """
        ),
        md(
            """
            **Inverting a mapping.** Swapping keys and values works when values are unique and
            hashable. With duplicate values the naive inverse loses entries; group instead.
            """
        ),
        code(
            """
            country_names = {"IN": "India", "NP": "Nepal", "LK": "Sri Lanka"}
            country_codes = {name: code for code, name in country_names.items()}
            print(f"{country_codes['Nepal']=}")
            city_by_person = {"asha": "Pune", "ravi": "Goa", "meena": "Pune"}
            naive_inverse = {city: person for person, city in city_by_person.items()}
            print(f"{naive_inverse=}  (asha was overwritten)")
            people_by_city: defaultdict[str, list[str]] = defaultdict(list)
            for person, city in city_by_person.items():
                people_by_city[city].append(person)
            print(f"{dict(people_by_city)=}")
            """
        ),
        md(
            """
            **Sorting by value.** Sort `items()` with a key on the value, then rebuild a dict
            (which keeps the sorted order). `max(d, key=d.get)` finds the key with the largest
            value.
            """
        ),
        code(
            """
            dish_ratings = {"dosa": 4.7, "idli": 4.2, "vada": 4.5}
            ratings_high_to_low = dict(sorted(dish_ratings.items(), key=lambda pair: pair[1], reverse=True))
            print(f"{ratings_high_to_low=}")
            print(f"{max(dish_ratings, key=dish_ratings.__getitem__)=}")
            print(f"{sorted(dish_ratings, key=dish_ratings.__getitem__)=}")
            """
        ),
        md(
            """
            **Safe nested access.** `config.get("db", {}).get("port")` avoids `KeyError` at each
            level. It fails when a key exists with the value `None` (the default is only used for
            *missing* keys); `(config.get(key) or {})` covers that. For deeper paths, a small
            helper is clearer.
            """
        ),
        code(
            '''
            service_config: dict[str, Any] = {"db": {"host": "localhost", "port": 5432}, "cache": None}
            print(f"{service_config.get('db', {}).get('port')=}")
            print(f"{service_config.get('queue', {}).get('url')=}")
            none_value_result = raised_error_name(lambda: service_config.get("cache", {}).get("ttl"))
            print(f"key present with None: {none_value_result}")
            print(f"{(service_config.get('cache') or {}).get('ttl')=}")


            def nested_get(mapping: Mapping[str, Any], *keys: str, default: object = None) -> object:
                """Follow keys through nested mappings; return default if any step is missing."""
                current_value: object = mapping
                for key in keys:
                    if not isinstance(current_value, Mapping) or key not in current_value:
                        return default
                    current_value = current_value[key]
                return current_value


            print(f"{nested_get(service_config, 'db', 'host')=}")
            print(f"{nested_get(service_config, 'cache', 'ttl', default=60)=}")
            '''
        ),
        md(
            """
            **Merging with precedence.** Later sources win in both `{**a, **b}` and `a | b`, so
            list the sources from lowest to highest priority. Both build a new dict; a `ChainMap`
            (1.6.7) gives the same lookups without copying.
            """
        ),
        code(
            """
            default_options = {"retries": 3, "timeout": 10, "region": "ap-south-1"}
            team_options = {"timeout": 30}
            request_options = {"retries": 5}
            merged_by_unpacking = {**default_options, **team_options, **request_options}
            merged_by_operator = default_options | team_options | request_options
            print(f"{merged_by_unpacking=}")
            print(f"{merged_by_unpacking == merged_by_operator=}")
            print(f"{dict(ChainMap(request_options, team_options, default_options)) == merged_by_operator=}")
            """
        ),
        md(
            """
            **Filtering with dict comprehensions.** Keep the pairs that pass a test, or keep only
            an allow-list of keys (for example before returning a record from an API).
            """
        ),
        code(
            """
            stock_levels = {"rice": 12, "dal": 0, "ghee": 2, "salt": 0}
            in_stock = {item: quantity for item, quantity in stock_levels.items() if quantity > 0}
            print(f"{in_stock=}")
            user_record = {"name": "Asha", "email": "asha@example.in", "password_hash": "x9f3"}
            public_field_names = {"name", "email"}
            public_record = {key: value for key, value in user_record.items() if key in public_field_names}
            print(f"{public_record=}")
            """
        ),
        md(
            """
            **Iterating with `items()`.** Unpack each pair in the `for` target; add `enumerate`
            for a running number. Iterating the dict itself gives only keys.
            """
        ),
        code(
            """
            menu_prices = {"dosa": 60, "idli": 40, "vada": 30}
            for line_number, (dish, price) in enumerate(menu_prices.items(), start=1):
                print(f"{line_number}. {dish:<6}{price:>5}")
            print(f"{sum(menu_prices.values())=}")
            """
        ),
        md(
            """
            **Converting to and from JSON.** A dict of strings, numbers, booleans, `None`, lists
            and dicts round-trips through `json`. Three traps: **non-string keys become strings**
            (so the round trip is not equal), tuple keys and `Decimal` values raise `TypeError`,
            and `True`/`None` become `true`/`null`.
            """
        ),
        code(
            """
            order_payload = {
                "order_id": 1001,
                "items": [{"sku": "TEA", "qty": 2}],
                "paid": True,
                "coupon": None,
            }
            payload_text = json.dumps(order_payload, sort_keys=True)
            print(payload_text)
            print(f"{json.loads(payload_text) == order_payload=}")
            int_key_dict = {1: "one", 2: "two"}
            int_key_round_trip = json.loads(json.dumps(int_key_dict))
            print(f"{int_key_round_trip=}, {int_key_round_trip == int_key_dict=}")
            print(f"tuple key: {raised_error_name(lambda: json.dumps({(1, 2): 'x'}))}")
            print(f"Decimal value: {raised_error_name(lambda: json.dumps({'rate': Decimal('1.5')}))}")
            print(json.dumps({"rate": Decimal("1.5")}, default=str))
            """
        ),
    ]


def _data_structure_cells() -> list[NotebookNode]:
    """1.6.13 Classic data structures with built-ins."""
    return [
        md(
            """
            ### 1.6.13 Classic data structures with built-ins

            Python has no `Stack`, `Queue` or `Graph` classes in the core language: the built-in
            containers already do the job.

            **Stack (LIFO): a `list` with `append` / `pop`.** Both work at the end, O(1). The
            bracket checker is the textbook stack exercise.
            """
        ),
        code(
            '''
            def brackets_balanced(text: str) -> bool:
                """Return True if every (, [ and { in text is closed in the right order."""
                closing_to_opening = {")": "(", "]": "[", "}": "{"}
                open_brackets: list[str] = []
                for character in text:
                    if character in "([{":
                        open_brackets.append(character)
                    elif character in closing_to_opening:
                        if not open_brackets or open_brackets.pop() != closing_to_opening[character]:
                            return False
                return not open_brackets


            undo_stack = ["type 'a'", "type 'b'", "bold"]
            print(f"{undo_stack[-1]=} (peek), {undo_stack.pop()=}, {undo_stack=}")
            print(f"{brackets_balanced('{[()]}')=}, {brackets_balanced('([)]')=}, {brackets_balanced('((')=}")
            '''
        ),
        md("**FIFO queue: a `deque` with `append` / `popleft`**, both O(1)."),
        code(
            """
            support_queue: deque[str] = deque()
            for ticket_title in ["login fails", "refund request", "typo on page"]:
                support_queue.append(ticket_title)
            while support_queue:
                print(f"serving: {support_queue.popleft()}")
            """
        ),
        md(
            """
            **Priority queue: `heapq` on a list.** `heapq` keeps a plain list in min-heap order:
            `heappush` and `heappop` are O(log n), and `heap[0]` is always the smallest item.
            Push tuples `(priority, sequence_number, task)`: the sequence number breaks ties in
            arrival order and stops Python from ever comparing two tasks. `heapify` turns a list
            into a heap in O(n); `nsmallest` / `nlargest` answer top-k questions.
            """
        ),
        code(
            """
            pending_jobs: list[tuple[int, int, str]] = []
            incoming_jobs = [(3, "send newsletter"), (1, "capture payment"), (2, "resize image"), (1, "refund")]
            for sequence_number, (priority, job_name) in enumerate(incoming_jobs):
                heapq.heappush(pending_jobs, (priority, sequence_number, job_name))
            print(f"{pending_jobs[0]=}  (smallest priority first)")
            while pending_jobs:
                priority, _sequence_number, job_name = heapq.heappop(pending_jobs)
                print(f"priority {priority}: {job_name}")
            response_times_ms = [120, 45, 300, 80, 95]
            heapq.heapify(response_times_ms)
            print(f"{response_times_ms[0]=}, {heapq.nlargest(2, [120, 45, 300, 80, 95])=}")
            """
        ),
        md(
            """
            *New in 3.14:* `heapq` gained public max-heap functions (`heapify_max`,
            `heappush_max`, `heappop_max`, …), so a max-heap no longer needs negated numbers.
            """
        ),
        code(
            """
            if sys.version_info >= (3, 14):
                bid_amounts = [120, 450, 300, 80]
                heapq.heapify_max(bid_amounts)
                heapq.heappush_max(bid_amounts, 500)
                print(f"{heapq.heappop_max(bid_amounts)=}, {heapq.heappop_max(bid_amounts)=}")
            else:
                print("max-heap functions need Python 3.14+; push negated values on older versions")
            """
        ),
        md(
            """
            **Graphs as `dict[str, list[str]]`, BFS with a `deque`, and a set of visited nodes.**
            An adjacency list maps each node to its neighbours. Breadth-first search explores in
            rings of increasing distance, so the first time it reaches the goal is along a
            shortest path (fewest edges). The `visited` set stops it from queueing a node twice:
            O(1) membership is the reason it is a set and not a list.
            """
        ),
        code(
            '''
            metro_lines: dict[str, list[str]] = {
                "Airport": ["Central", "Park"],
                "Central": ["Airport", "Market", "Stadium"],
                "Park": ["Airport", "Museum"],
                "Market": ["Central", "Harbour"],
                "Stadium": ["Central"],
                "Museum": ["Park", "Harbour"],
                "Harbour": ["Market", "Museum"],
            }


            def bfs_shortest_path(graph: dict[str, list[str]], start: str, goal: str) -> list[str] | None:
                """Return a path with the fewest edges from start to goal, or None if unreachable."""
                visited = {start}
                came_from: dict[str, str] = {}
                frontier = deque([start])
                while frontier:
                    node = frontier.popleft()
                    if node == goal:
                        path = [node]
                        while path[-1] != start:
                            path.append(came_from[path[-1]])
                        return path[::-1]
                    for neighbour in graph.get(node, []):
                        if neighbour not in visited:
                            visited.add(neighbour)
                            came_from[neighbour] = node
                            frontier.append(neighbour)
                return None


            print(f"{bfs_shortest_path(metro_lines, 'Airport', 'Harbour')=}")
            print(f"{bfs_shortest_path(metro_lines, 'Stadium', 'Museum')=}")
            print(f"{bfs_shortest_path(metro_lines, 'Airport', 'Moon')=}")
            '''
        ),
        md(
            """
            **DFS with an explicit stack.** Depth-first search swaps the queue for a stack (a
            `list`). Pushing neighbours in reverse makes the visit order match the recursive
            version, without Python's recursion limit (Unit 1.10).
            """
        ),
        code(
            '''
            def dfs_order(graph: dict[str, list[str]], start: str) -> list[str]:
                """Return nodes in depth-first visit order, using a list as the stack."""
                visited: set[str] = set()
                visit_order: list[str] = []
                stack = [start]
                while stack:
                    node = stack.pop()
                    if node in visited:
                        continue
                    visited.add(node)
                    visit_order.append(node)
                    for neighbour in reversed(graph.get(node, [])):
                        if neighbour not in visited:
                            stack.append(neighbour)
                return visit_order


            print(f"{dfs_order(metro_lines, 'Airport')=}")
            print(f"{len(dfs_order(metro_lines, 'Airport')) == len(metro_lines)=}  (all reachable)")
            '''
        ),
        md(
            """
            **A trie as nested dicts.** Each level maps one character to the next level;
            a special key marks the end of a word. Prefix search walks down the prefix, then
            collects every word below it. `setdefault` builds missing levels in one line.
            """
        ),
        code(
            '''
            END_OF_WORD = "$"


            def trie_insert(trie: dict[str, Any], word: str) -> None:
                """Add word to a nested-dict trie."""
                node = trie
                for character in word:
                    node = node.setdefault(character, {})
                node[END_OF_WORD] = True


            def trie_words_with_prefix(trie: dict[str, Any], prefix: str) -> list[str]:
                """Return every stored word starting with prefix, sorted."""
                node = trie
                for character in prefix:
                    if character not in node:
                        return []
                    node = node[character]
                found_words: list[str] = []
                pending = [(node, prefix)]
                while pending:
                    current_node, letters = pending.pop()
                    for key, child in current_node.items():
                        if key == END_OF_WORD:
                            found_words.append(letters)
                        else:
                            pending.append((child, letters + key))
                return sorted(found_words)


            city_trie: dict[str, Any] = {}
            for city_name in ["pune", "punjab", "puri", "patna", "goa"]:
                trie_insert(city_trie, city_name)
            print(f"{trie_words_with_prefix(city_trie, 'pu')=}, {trie_words_with_prefix(city_trie, 'x')=}")
            print(json.dumps(city_trie["g"]))
            '''
        ),
        md(
            """
            **A singly linked list with a small node class** (a preview of Phase 2, where classes
            are covered properly). Pushing to the front and inserting after a node you already
            hold are O(1); finding the n-th item is O(n). In everyday Python a `list` or `deque`
            is almost always the better choice; the point here is to see the pointer structure.
            The annotation `LinkedListNode | None` inside the class works unquoted because
            annotations are evaluated lazily since 3.14 (PEP 649).
            """
        ),
        code(
            '''
            class LinkedListNode:
                """One node of a singly linked list."""

                def __init__(self, value: str, next_node: LinkedListNode | None = None) -> None:
                    self.value = value
                    self.next_node = next_node


            def linked_list_values(head: LinkedListNode | None) -> list[str]:
                """Walk the list from head and collect the values."""
                collected_values: list[str] = []
                current_node = head
                while current_node is not None:
                    collected_values.append(current_node.value)
                    current_node = current_node.next_node
                return collected_values


            playlist_head = LinkedListNode("intro", LinkedListNode("verse", LinkedListNode("chorus")))
            playlist_head = LinkedListNode("countdown", playlist_head)  # O(1) push to the front
            verse_node = playlist_head.next_node.next_node
            verse_node.next_node = LinkedListNode("bridge", verse_node.next_node)  # O(1) insert after
            print(f"{linked_list_values(playlist_head)=}")
            '''
        ),
        md(
            """
            **Big-O summary** for every operation used in this section (average case; *n* items,
            *k* items involved).

            | Structure | Operation | Built-in used | Cost |
            | --- | --- | --- | --- |
            | Stack | push / pop / peek | `list.append` / `list.pop()` / `items[-1]` | O(1) amortized / O(1) / O(1) |
            | FIFO queue | enqueue / dequeue | `deque.append` / `deque.popleft` | O(1) / O(1) |
            | FIFO queue (wrong tool) | dequeue | `list.pop(0)` | O(n) |
            | Priority queue | push / pop / peek | `heappush` / `heappop` / `heap[0]` | O(log n) / O(log n) / O(1) |
            | Priority queue | build / top k | `heapify` / `nlargest(k, …)` | O(n) / O(n log k) |
            | Visited set | add / membership | `set.add` / `in` | O(1) / O(1) |
            | Graph | neighbours of a node | `graph[node]` | O(1) to find, O(degree) to scan |
            | BFS / DFS | whole traversal | `deque` / `list` + `set` | O(V + E) |
            | Trie | insert / prefix lookup | nested `dict` + `setdefault` | O(word length) / O(prefix length + matches) |
            | Linked list | push front / insert after a held node | node objects | O(1) / O(1) |
            | Linked list | find n-th item / search | walk `next_node` | O(n) |
            """
        ),
    ]


def _use_case_cells() -> list[NotebookNode]:
    """1.6.14 Real-world use cases."""
    return [
        md(
            """
            ### 1.6.14 Real-world use cases

            **`dict` (1 of 2): parsed JSON payloads, lookup tables, caches.** A webhook body
            parses into nested dicts; a constant dict maps country codes to names; a dict keyed by
            the arguments caches an expensive call (`functools.cache`, Unit 1.12, does this for
            you).
            """
        ),
        code(
            '''
            webhook_body = '{"event": "payment.captured", "payment": {"id": "pay_29", "amount": 49900}}'
            webhook_payload = json.loads(webhook_body)
            amount_in_rupees = Decimal(webhook_payload["payment"]["amount"]) / 100
            print(f"{webhook_payload['event']=}, {amount_in_rupees=}")

            COUNTRY_NAMES = {"IN": "India", "US": "United States", "JP": "Japan"}
            print(f"{COUNTRY_NAMES.get('JP', 'unknown')=}, {COUNTRY_NAMES.get('XX', 'unknown')=}")

            exchange_rate_cache: dict[tuple[str, str], Decimal] = {}


            def exchange_rate(source_currency: str, target_currency: str) -> Decimal:
                """Return a rate, computing it only on the first request for each pair."""
                cache_key = (source_currency, target_currency)
                if cache_key not in exchange_rate_cache:
                    print(f"  (slow lookup for {cache_key})")
                    exchange_rate_cache[cache_key] = (
                        Decimal("83.25") if cache_key == ("USD", "INR") else Decimal("1")
                    )
                return exchange_rate_cache[cache_key]


            print(f"{exchange_rate('USD', 'INR')=}")
            print(f"{exchange_rate('USD', 'INR')=}  (served from the cache)")
            '''
        ),
        md(
            """
            **`dict` (2 of 2): config objects, routing/dispatch tables, records indexed by ID.**
            A dispatch table maps a request to a handler function, replacing a long `if`/`elif`
            chain; web frameworks (Phase 6) route this way.
            """
        ),
        code(
            '''
            server_config = {"debug": False, "workers": 4, "allowed_hosts": ["shop.example.in"]}
            products_by_sku = {
                product["sku"]: product
                for product in [{"sku": "TEA", "price": 249}, {"sku": "DAL", "price": 162}]
            }


            def list_products(request_body: dict[str, Any]) -> str:
                """Handle GET /products."""
                return f"200 OK: {sorted(products_by_sku)}"


            def create_product(request_body: dict[str, Any]) -> str:
                """Handle POST /products."""
                products_by_sku[request_body["sku"]] = request_body
                return f"201 Created: {request_body['sku']}"


            ROUTES: dict[tuple[str, str], Callable[[dict[str, Any]], str]] = {
                ("GET", "/products"): list_products,
                ("POST", "/products"): create_product,
            }


            def dispatch(method: str, path: str, request_body: dict[str, Any]) -> str:
                """Look up the handler for (method, path) and call it."""
                handler = ROUTES.get((method, path))
                return handler(request_body) if handler else "404 Not Found"


            print(dispatch("POST", "/products", {"sku": "GHEE", "price": 640}))
            print(dispatch("GET", "/products", {}))
            print(dispatch("DELETE", "/products", {}))
            print(f"{server_config['workers']=}, {products_by_sku['GHEE']['price']=}")
            '''
        ),
        md(
            """
            **`set`: deduplicating emails, permission checks, tags, comparing datasets, visited
            sets.** Normalise before deduplicating (as `normalize_email` did in 1.4.7). Comparing
            two exports of user IDs is one subtraction each way.
            """
        ),
        code(
            """
            signup_emails = ["Asha@Example.in", "ravi@example.in", " asha@example.in", "RAVI@example.in"]
            unique_emails = {email.strip().lower() for email in signup_emails}
            print(f"{sorted(unique_emails)=}")

            ROLE_PERMISSIONS = {
                "viewer": {"read"},
                "editor": {"read", "write"},
                "admin": {"read", "write", "delete"},
            }
            print(f"{'delete' in ROLE_PERMISSIONS['editor']=}")
            print(f"{ROLE_PERMISSIONS['viewer'] <= ROLE_PERMISSIONS['admin']=}")

            post_tags = {"python", "dicts", "performance"}
            followed_tags = {"python", "rust"}
            print(f"{sorted(post_tags & followed_tags)=}  (why this post is in the feed)")

            users_in_billing = {101, 102, 103, 105}
            users_in_crm = {101, 103, 104}
            print(f"{users_in_billing - users_in_crm=}, {users_in_crm - users_in_billing=}")
            print("visited set: see bfs_shortest_path and dfs_order in 1.6.13")
            """
        ),
        md(
            """
            **`frozenset` / `frozendict`: cache keys, sets of sets, immutable configuration.** A
            search filter given as a dict can be turned into a cache key with
            `frozenset(filters.items())` (or `frozendict(filters)` on 3.15), so the same filters in
            any order hit the same entry.
            """
        ),
        code(
            """
            search_cache: dict[frozenset[tuple[str, str]], list[str]] = {}
            first_filters = {"city": "Pune", "cuisine": "south indian"}
            search_cache[frozenset(first_filters.items())] = ["Dosa Corner", "Idli House"]
            same_filters_reordered = {"cuisine": "south indian", "city": "Pune"}
            print(f"{search_cache[frozenset(same_filters_reordered.items())]=}")

            ingredient_combos = {frozenset({"rice", "dal"}), frozenset({"dal", "rice"}), frozenset({"rice"})}
            print(f"{len(ingredient_combos)=}  (a set of sets; order inside each set ignored)")

            if sys.version_info >= (3, 15):
                FEATURE_FLAGS = frozendict(new_checkout=True, dark_mode=False)
                reordered_flags = frozendict(dark_mode=False, new_checkout=True)
                print(f"{FEATURE_FLAGS['new_checkout']=}")
                print(f"usable as one cache key: {hash(FEATURE_FLAGS) == hash(reordered_flags)}")
            else:
                print("frozendict needs Python 3.15; skipped")
            """
        ),
        md(
            """
            **`deque` (1 of 2): BFS queues, sliding windows, last N events.** `bfs_shortest_path`
            in 1.6.13 already uses a deque as its queue. A `maxlen` deque gives a moving average
            over the last readings and an "N most recent events" history.
            """
        ),
        code(
            """
            print(f"{bfs_shortest_path(metro_lines, 'Park', 'Market')=}  (a deque inside)")

            latency_window: deque[int] = deque(maxlen=3)
            for latency_ms in [120, 80, 100, 400, 90]:
                latency_window.append(latency_ms)
                moving_average = sum(latency_window) / len(latency_window)
                print(f"latest {latency_ms:>3} ms → moving average {moving_average:6.1f}")

            recent_events: deque[str] = deque(maxlen=2)
            for event_name in ["login", "view cart", "add item", "checkout"]:
                recent_events.append(event_name)
            print(f"{list(recent_events)=}")
            """
        ),
        md(
            """
            **`deque` (2 of 2): rate-limiter timestamps.** A sliding-window limiter keeps the
            times of recent requests; it drops timestamps older than the window from the left and
            allows a request if fewer than `limit` remain. The times here are fixed numbers, so
            the output is deterministic.
            """
        ),
        code(
            '''
            def allow_request(
                request_times: deque[float], now: float, limit: int, window_seconds: float
            ) -> bool:
                """Allow at most limit requests in any window_seconds-long window."""
                while request_times and now - request_times[0] >= window_seconds:
                    request_times.popleft()
                if len(request_times) < limit:
                    request_times.append(now)
                    return True
                return False


            client_request_times: deque[float] = deque()
            for request_time in [0.0, 0.2, 0.4, 0.6, 1.1, 1.3]:
                allowed = allow_request(client_request_times, request_time, limit=3, window_seconds=1.0)
                print(f"t={request_time:.1f}s: {'allowed' if allowed else 'rejected (429)'}")
            '''
        ),
        md(
            """
            **`Counter`: word frequencies, page-view analytics, inventory tallies.**
            """
        ),
        code(
            """
            review_text = "Great dosa. Great chutney! The dosa was crisp; the chutney was fresh."
            word_frequencies = Counter(re.findall(r"[a-z]+", review_text.lower()))
            print(f"{word_frequencies.most_common(3)=}")

            request_paths = ["/home", "/product/7", "/home", "/cart", "/product/7", "/home"]
            print(f"{Counter(request_paths).most_common(2)=}")

            inventory = Counter(tea=40, rice=25)
            inventory += Counter(tea=10, ghee=12)  # shipment received
            inventory -= Counter(rice=25)  # sold out: the zero count is dropped
            print(f"{inventory=}, {inventory.total()=}")
            """
        ),
        md(
            """
            **`defaultdict`: grouping and adjacency lists.** Grouping records by a field (here
            invoices by month; grouping orders by customer is Lab 1.6, exercise 1) and building an
            adjacency list from an edge list are the same three lines.
            """
        ),
        code(
            """
            invoices = [("2026-09", 1200), ("2026-10", 800), ("2026-09", 450), ("2026-10", 300)]
            amounts_by_month: defaultdict[str, list[int]] = defaultdict(list)
            for month, amount in invoices:
                amounts_by_month[month].append(amount)
            print(f"{ {month: sum(amounts) for month, amounts in amounts_by_month.items()}=}")

            road_edges = [("Pune", "Mumbai"), ("Pune", "Nashik"), ("Mumbai", "Goa")]
            road_graph: defaultdict[str, list[str]] = defaultdict(list)
            for city_a, city_b in road_edges:
                road_graph[city_a].append(city_b)
                road_graph[city_b].append(city_a)
            print(f"{dict(road_graph)=}")
            """
        ),
        md(
            """
            **`OrderedDict`: LRU caches; `ChainMap`: CLI > environment > defaults.** An LRU cache
            needs exactly two `OrderedDict` moves: `move_to_end` on every hit and
            `popitem(last=False)` when full (Lab 1.6, exercise 4, wraps them in a class). For
            configuration, `argparse` with `argument_default=argparse.SUPPRESS` leaves unset
            options out of the result, so they fall through to the next layer of the ChainMap.
            """
        ),
        code(
            """
            page_cache = OrderedDict([("/home", "<home>"), ("/cart", "<cart>")])
            page_cache.move_to_end("/home")  # a hit on /home makes it most recent
            page_cache["/pay"] = "<pay>"
            if len(page_cache) > 2:
                print(f"evicted {page_cache.popitem(last=False)[0]}")
            print(f"{list(page_cache)=}")

            argument_parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
            argument_parser.add_argument("--port", type=int)
            argument_parser.add_argument("--debug", action="store_true")
            cli_settings = vars(argument_parser.parse_args(["--debug"]))
            fake_environment = {"APP_PORT": "9000", "HOME": "/home/asha"}
            env_settings = {
                name.removeprefix("APP_").lower(): int(value)
                for name, value in fake_environment.items()
                if name.startswith("APP_")
            }
            settings = ChainMap(cli_settings, env_settings, {"port": 8000, "debug": False, "host": "0.0.0.0"})
            print(f"{dict(settings)=}")
            """
        ),
    ]


def _lab_cells() -> list[NotebookNode]:
    """Lab 1.6."""
    return [
        md(
            """
            ### Lab 1.6

            Five exercises on one small order dataset. For each, replace the
            `raise NotImplementedError` in the stub, then run the check cell. Until then the
            checks print FAIL; that is expected.

            Run the next cell first: it defines the `Order` record, `SAMPLE_ORDERS` and
            `PRODUCT_CATALOG`, a `frozendict` of SKU → unit price (a read-only
            `MappingProxyType` on kernels older than 3.15). `SOAP-3PK` is deliberately missing
            from the catalog.
            """
        ),
        code(
            '''
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
            catalog_prices = {
                "TEA-500G": Decimal("249.00"),
                "RICE-5KG": Decimal("525.50"),
                "GHEE-1L": Decimal("640.00"),
                "DAL-1KG": Decimal("162.25"),
            }
            if sys.version_info >= (3, 15):
                PRODUCT_CATALOG: Mapping[str, Decimal] = frozendict(catalog_prices)
            else:
                PRODUCT_CATALOG = types.MappingProxyType(catalog_prices)
            print(f"{len(SAMPLE_ORDERS)=}, {type(PRODUCT_CATALOG).__name__=}")
            '''
        ),
        md(
            """
            #### Exercise 1 — `group_orders_by_customer(orders)`

            Group orders by customer with a `defaultdict(list)`. Return a **plain `dict`** (so a
            missing customer raises `KeyError` instead of being created), with customers in the
            order they first appear and each customer's orders in input order.
            """
        ),
        code(
            '''
            def group_orders_by_customer(orders: Iterable[Order]) -> dict[str, list[Order]]:
                """Return {customer: [their orders in input order]} as a plain dict."""
                raise NotImplementedError("Lab 1.6: implement group_orders_by_customer()")
            '''
        ),
        md(
            """
            The check cell compares order IDs per customer, the customer order, the return type,
            and the missing-customer behaviour.
            """
        ),
        code(
            """
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
            """
        ),
        md(
            r"""
            #### Exercise 2 — `top_k_words(text, k)`

            Return the `k` most frequent words as `(word, count)` pairs. Words are compared
            **case-insensitively** (`casefold`) and **ignoring punctuation**: a word is a run of
            letters or digits, `re.findall(r"[^\W_]+", ...)`. Sort by count descending, then
            **ties alphabetically**. `k <= 0` gives `[]`.

            > **Note:** `Counter.most_common` breaks ties by first appearance, not alphabetically,
            > so it is not enough on its own.
            """
        ),
        code(
            '''
            def top_k_words(text: str, k: int) -> list[tuple[str, int]]:
                """Return the k most frequent words, ties broken alphabetically."""
                raise NotImplementedError("Lab 1.6: implement top_k_words()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            nursery_text = "The cat and the hat. THE CAT sat; a bat sat!"
            run_checks(
                [
                    ("top 3", lambda: top_k_words(nursery_text, 3), [("the", 3), ("cat", 2), ("sat", 2)]),
                    (
                        "ties alphabetical",
                        lambda: top_k_words(nursery_text, 5),
                        [("the", 3), ("cat", 2), ("sat", 2), ("a", 1), ("and", 1)],
                    ),
                    ("k larger than vocabulary", lambda: len(top_k_words(nursery_text, 50)), 7),
                    ("k = 0", lambda: top_k_words(nursery_text, 0), []),
                    ("empty text", lambda: top_k_words("", 3), []),
                    ("caseless and unicode", lambda: top_k_words("Café café CAFÉ, tea", 1), [("café", 3)]),
                    ("underscore splits words", lambda: top_k_words("snake_case snake", 1), [("snake", 2)]),
                ]
            )
            """
        ),
        md(
            """
            #### Exercise 3 — `merge_configs(defaults, env, cli)`

            Return a `ChainMap` where command-line values beat environment values, which beat
            defaults. A `None` value in `cli` means "flag not given" and must not hide the lower
            layers. Writes to the result must not change any of the three input dicts (put a
            fresh dict first in the chain).
            """
        ),
        code(
            '''
            def merge_configs(
                defaults: Mapping[str, object], env: Mapping[str, object], cli: Mapping[str, object]
            ) -> ChainMap[str, object]:
                """Layer cli > env > defaults; None in cli means "not given"."""
                raise NotImplementedError("Lab 1.6: implement merge_configs()")
            '''
        ),
        md(
            """
            The check cell defines `writes_leave_inputs_alone`, which writes through the result
            and confirms the three inputs did not change.
            """
        ),
        code(
            '''
            default_config = {"host": "localhost", "port": 8000, "debug": False, "log_level": "INFO"}
            env_config = {"port": 9000, "log_level": "WARNING"}
            cli_config = {"debug": True, "port": None}


            def writes_leave_inputs_alone() -> bool:
                """Write through merge_configs' result and check that no input dict changed."""
                inputs_before = (dict(default_config), dict(env_config), dict(cli_config))
                merged_config = merge_configs(default_config, env_config, cli_config)
                merged_config["host"] = "example.in"
                merged_config["timeout"] = 30
                return (default_config, env_config, cli_config) == inputs_before


            run_checks(
                [
                    (
                        "returns a ChainMap",
                        lambda: type(merge_configs(default_config, env_config, cli_config)).__name__,
                        "ChainMap",
                    ),
                    (
                        "precedence cli > env > defaults",
                        lambda: dict(merge_configs(default_config, env_config, cli_config)),
                        {"host": "localhost", "port": 9000, "debug": True, "log_level": "WARNING"},
                    ),
                    (
                        "None in cli is ignored",
                        lambda: merge_configs(default_config, env_config, cli_config)["port"],
                        9000,
                    ),
                    ("writes leave inputs alone", writes_leave_inputs_alone, True),
                    ("empty layers", lambda: dict(merge_configs({"a": 1}, {}, {})), {"a": 1}),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 4 — `LRUCache(capacity)`

            A least-recently-used cache on an `OrderedDict`:

            - `get(key, default=None)`: return the value and mark the key most recently used;
              return `default` on a miss.
            - `put(key, value)`: insert or update, mark it most recently used, and if the cache
              is now over capacity evict the **least** recently used key.
            - `len(cache)` and `key in cache` (membership does **not** change recency).
            - `capacity < 1` raises `ValueError`.
            """
        ),
        code(
            '''
            class LRUCache:
                """A fixed-capacity least-recently-used cache built on OrderedDict."""

                def __init__(self, capacity: int) -> None:
                    raise NotImplementedError("Lab 1.6: implement LRUCache.__init__()")

                def get(self, key: Hashable, default: object = None) -> object:
                    """Return the cached value (marking it recent) or default."""
                    raise NotImplementedError("Lab 1.6: implement LRUCache.get()")

                def put(self, key: Hashable, value: object) -> None:
                    """Store value, evicting the least recently used key if over capacity."""
                    raise NotImplementedError("Lab 1.6: implement LRUCache.put()")

                def __len__(self) -> int:
                    raise NotImplementedError("Lab 1.6: implement LRUCache.__len__()")

                def __contains__(self, key: object) -> bool:
                    raise NotImplementedError("Lab 1.6: implement LRUCache.__contains__()")
            '''
        ),
        md(
            """
            The check cell replays short sequences of operations and records what the cache
            returns.
            """
        ),
        code(
            '''
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


            run_checks(
                [
                    ("get refreshes recency", lru_basic_trace, [1, None, 3, 2, True]),
                    ("put updates and refreshes", lru_update_trace, [10, False, 2]),
                    ("in does not refresh", lru_contains_trace, False),
                    ("get default on miss", lambda: LRUCache(1).get("x", "fallback"), "fallback"),
                    ("capacity 0 raises", lambda: raised_error_name(lambda: LRUCache(0)), "ValueError"),
                ]
            )
            '''
        ),
        md(
            """
            #### Exercise 5 — order-analytics pipeline

            Write `analyze_orders(orders, catalog)` returning a dict with exactly these keys:

            | Key | Value | Build it with |
            | --- | --- | --- |
            | `revenue_by_customer` | `dict[str, Decimal]`: quantity × catalog price, catalog SKUs only | `defaultdict(Decimal)` |
            | `top_skus` | the 3 best-selling catalog SKUs by units, as `(sku, units)` pairs | `Counter.most_common(3)` |
            | `unique_customer_count` | number of distinct customers (all orders) | `set` |
            | `recent_order_ids` | IDs of the last 5 orders, oldest first, as a `list` | `deque(maxlen=5)` |
            | `unknown_skus` | sorted list of SKUs missing from the catalog | `set`, then `sorted` |

            Orders with an unknown SKU count towards customers and recent orders, but not towards
            revenue or `top_skus`. Return plain `dict`/`list` values, not the helper containers.
            """
        ),
        code(
            '''
            def analyze_orders(orders: Iterable[Order], catalog: Mapping[str, Decimal]) -> dict[str, object]:
                """Summarise orders: revenue, top SKUs, customers, recent IDs, unknown SKUs."""
                raise NotImplementedError("Lab 1.6: implement analyze_orders()")
            '''
        ),
        md("Run the checks."),
        code(
            """
            run_checks(
                [
                    (
                        "revenue by customer",
                        lambda: analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["revenue_by_customer"],
                        {"asha": Decimal("1462.50"), "ravi": Decimal("774.50"), "meena": Decimal("1798.00")},
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
                            type(analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)["revenue_by_customer"]).__name__
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
            """
        ),
    ]


def _recap_cells() -> list[NotebookNode]:
    """Recap for Unit 1.6."""
    return [
        md(
            r"""
            ### Recap — Unit 1.6

            | Concept | One-line takeaway | JS equivalent |
            | --- | --- | --- |
            | `dict` internals | Compact hash table: sparse indices + dense entries; insertion-ordered; O(1) average | `Map` |
            | Probing and resizing | Open addressing with a perturbed probe; table kept ≤ 2/3 full, resized in O(n) rarely | — |
            | Key-sharing dicts | Instances of one class share a key table (PEP 412) | hidden classes in V8 |
            | Hashable | Stable `__hash__` that agrees with `__eq__`; mutable built-ins are unhashable | `Map` uses SameValueZero, no hashing contract |
            | `1 == 1.0 == True` | One dict key: first key kept, last value wins | `obj[1]` and `obj["1"]` collide instead |
            | String-hash randomization | Per-process SipHash key against hash flooding; `PYTHONHASHSEED` | — |
            | Access | `d[k]` raises `KeyError`; `get`, `setdefault`, `in` (keys) | `obj[k]` gives `undefined` |
            | Merge | `\|`, `\|=`, `{**a, **b}`, `update`; the right side wins | `{...a, ...b}` |
            | Views | `keys`/`values`/`items` are live; keys and items are set-like | `Object.keys()` returns a snapshot array |
            | `dict.fromkeys` | Every key shares one value object | `Array(n).fill([])` |
            | Size change while iterating | `RuntimeError`; iterate over `list(d)` | silently allowed |
            | `SimpleNamespace` | Attribute access over a dict | plain object |
            | `frozendict` / `MappingProxyType` | Immutable and hashable (3.15) / read-only live view | `Object.freeze` (shallow, not a key) |
            | `set` / `frozenset` | Hash set with `\| & - ^`; methods take any iterable; `frozenset` is hashable | `Set` (+ ES2025 methods) |
            | `deque` | O(1) at both ends; `maxlen` ring buffer | `shift()` is O(n) |
            | `Counter` | Counts, `most_common`, `total`, `+ - & \|`; missing keys are 0 | `reduce` into an object |
            | `defaultdict` | Factory runs on a missing-key **read** (`__missing__`) | `(m[k] ??= [])` |
            | `OrderedDict` | `move_to_end`, `popitem(last=False)`, order-sensitive `==` | `Map` delete + set |
            | `ChainMap` | Layered lookups without copying; writes go to the first map | `Object.assign` (copies) |
            | `heapq` | Min-heap on a list; `(priority, seq, item)` tuples; max-heap API in 3.14 | no built-in |
            | JSON | Non-string keys become strings; tuples and `Decimal` need help | `JSON.stringify` |

            **Further reading**

            - [Mapping types — `dict`](https://docs.python.org/3/library/stdtypes.html#mapping-types-dict),
              [set types — `set`, `frozenset`](https://docs.python.org/3/library/stdtypes.html#set-types-set-frozenset),
              [`frozendict`](https://docs.python.org/3.15/library/stdtypes.html#frozendict)
            - [`collections`](https://docs.python.org/3/library/collections.html),
              [`heapq`](https://docs.python.org/3/library/heapq.html),
              [`types.MappingProxyType` / `SimpleNamespace`](https://docs.python.org/3/library/types.html)
            - [`object.__hash__`](https://docs.python.org/3/reference/datamodel.html#object.__hash__),
              [`PYTHONHASHSEED`](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONHASHSEED),
              [`json`](https://docs.python.org/3/library/json.html)
            - [PEP 412 — Key-sharing dictionary](https://peps.python.org/pep-0412/),
              [PEP 456 — Secure and interchangeable hash algorithm](https://peps.python.org/pep-0456/),
              [PEP 468 — Preserving keyword argument order](https://peps.python.org/pep-0468/)
            - [PEP 584 — Add union operators to dict](https://peps.python.org/pep-0584/),
              [PEP 814 — Add frozendict built-in type](https://peps.python.org/pep-0814/),
              [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/)
            - [Time complexity of CPython operations](https://wiki.python.org/moin/TimeComplexity)
            """
        ),
    ]


def cells() -> list[NotebookNode]:
    """Return the cells for Unit 1.6 and Lab 1.6."""
    return [
        *_overview_cells(),
        *_dict_internals_cells(),
        *_hashing_cells(),
        *_dict_methods_cells(),
        *_js_comparison_cells(),
        *_immutable_mapping_cells(),
        *_set_cells(),
        *_collections_cells(),
        *_choosing_cells(),
        *_dict_reference_cells(),
        *_set_reference_cells(),
        *_collections_reference_cells(),
        *_pattern_cells(),
        *_data_structure_cells(),
        *_use_case_cells(),
        *_lab_cells(),
        *_recap_cells(),
    ]
