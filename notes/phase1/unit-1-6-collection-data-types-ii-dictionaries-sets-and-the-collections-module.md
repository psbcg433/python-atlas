# Unit 1.6 — Collection Data Types II: Dictionaries, Sets and the collections Module

[← Previous](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md) · [Index](README.md) · [Next →](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md)

Unit 1.5 covered the sequence types, where you find things by position. This unit
covers the hash-based containers, where you find things by *key*: `dict`, `set`,
`frozenset`, the new `frozendict`, and the specialised containers in the
`collections` module. Along the way you will see how CPython lays a dict out in
memory, what "hashable" really means, and how to build stacks, queues, graphs and
tries from nothing but built-ins.

## What you will learn

- How a `dict` is stored (compact hash table, probing, resizing, key sharing) and
  why lookups are O(1) on average.
- The hashing contract, and how to predict which keys collapse into one.
- The complete `dict` and `set` APIs, including views, merge operators and in-place
  set algebra.
- When to choose `dict`, `frozendict`, `MappingProxyType`, `set`, `frozenset`, or one
  of the `collections` types (`deque`, `Counter`, `defaultdict`, `OrderedDict`,
  `ChainMap`).
- How to build stacks, queues, priority queues, graphs, tries and linked lists from
  built-ins.

## JavaScript → Python bridge

If you know JavaScript, most of this unit maps onto `Object`, `Map` and `Set`. The
table lists the spots where your JavaScript habits will mislead you.

| JavaScript | Python | The difference that bites |
| --- | --- | --- |
| `{dosa: 60}` | `{"dosa": 60}` | Keys are expressions; bare `dosa` is a variable |
| `prices.dosa` | `prices["dosa"]` | No dot access; a missing key raises `KeyError` |
| `new Map()`, object keys | `dict`, any hashable key | Lists, dicts and sets are rejected as keys |
| `obj[1]` same as `obj["1"]` | `1` and `"1"` differ | But `1`, `1.0` and `True` are one key |
| `{...defaults, ...overrides}` | `defaults \| overrides` | Also `{**a, **b}`; `\|=` updates in place |
| `new Set([1, 2])` | `{1, 2}` or `set(...)` | `{}` is an empty **dict**; use `set()` |
| `a.union(b)` (ES2025) | `a \| b` or `a.union(b)` | Operators need sets on both sides |
| `Object.freeze(obj)` | `frozendict(...)` | New in 3.15, and hashable |
| `queue.shift()` | `queue.popleft()` | O(1) on a `deque`; `list.pop(0)` is O(n) |
| `(groups[k] ??= []).push(x)` | `defaultdict(list)` | Inserts on every missing-key *read* |

> **Note:** sets of strings print in an order that changes between interpreter runs,
> because string hashes are randomized per process (see 1.6.2). The examples print
> `sorted(...)` of such sets so the outputs shown here stay stable.

> **Note:** a few output lines are longer than a phone screen. They are wrapped at a
> comma or a space, and the continuation is indented by two spaces. Nothing else in
> the outputs is changed.

The examples in this unit use a small helper, `raised_error_name`, which calls a
function and returns the name of the exception it raised. It lets one line show
"this raises `KeyError`" without stopping the program. `LogEntry` is the record
type from Unit 1.5, reused in 1.6.12.

```python
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
from collections import (
    ChainMap,
    Counter,
    OrderedDict,
    defaultdict,
    deque,
    namedtuple,
)
from collections.abc import (
    Callable,
    Hashable,
    Iterable,
    Mapping,
    MutableMapping,
)
from decimal import Decimal
from typing import Any, NamedTuple


def raised_error_name(thunk: Callable[[], object]) -> str:
    """Call thunk and return the name of the exception it raised."""
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
```

```text
sys.version_info[:2]=(3, 15)
```

## 1.6.1 Dictionaries (`dict`) — internals

A dictionary maps keys to values, and finding the value for a key takes the same
time whether the dict holds ten entries or ten million. That is possible because a
dict is a **hash table**: the key is turned into a number (its *hash*), and the
number says where in a table to look. You never scan the entries one by one.

### The compact layout

Since CPython 3.6, a dict is a **compact hash table** made of two arrays:

- a sparse **indices** array: one small integer per slot (1 byte each while the
  table has at most 128 slots), holding either "empty" or the position of an entry;
- a dense **entries** array: rows of `(hash, key, value)`, appended in insertion
  order.

To look up a key, CPython computes `hash(key)`, picks a slot with
`hash & (table_size - 1)` (the table size is always a power of two, so this is a
cheap "modulo"), reads the entry position stored in that slot, and then compares the
stored hash and key with the one you asked for. Because new entries are always
*appended* to the entries array, iterating a dict simply walks that array from the
start. That is why **insertion order is guaranteed**: it was an implementation
detail in 3.6 and became a language rule in 3.7.

The split also saves memory. Only the 1-byte indices are sparse (some slots must stay
empty for hashing to work); the wide 24-byte rows are packed tightly.

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

Order follows two simple rules. Replacing the value of an existing key rewrites its
row in place, so the key keeps its position. Deleting a key and inserting it again
appends a new row, so the key moves to the end.

```python
menu_prices = {"dosa": 60, "idli": 40, "vada": 30}
menu_prices["upma"] = 45
menu_prices["dosa"] = 65  # replacing a value keeps the original position
del menu_prices["idli"]
menu_prices["idli"] = 40  # re-inserting goes to the end
print(f"{list(menu_prices)=}")
print(f"{menu_prices=}")
```

```text
list(menu_prices)=['dosa', 'vada', 'upma', 'idli']
menu_prices={'dosa': 65, 'vada': 30, 'upma': 45, 'idli': 40}
```

In JavaScript, a `Map` also keeps insertion order, but a plain object does not
quite: integer-like keys are listed first in ascending order. A Python dict has no
such exception (1.6.4).

### Open addressing with perturbed probing

Two different keys can land in the same slot: a *collision*. Many hash tables (Java's
`HashMap`, for example) keep a linked list per slot. CPython instead uses **open
addressing**: it probes other slots of the same table until it finds the key or an
empty slot. The recurrence, from `Objects/dictobject.c`, mixes in the high bits of
the hash a few at a time, so two keys that collide on the first slot soon follow
different paths:

```text
perturb = hash
slot = hash & mask
while slot is taken by a different key:
    perturb >>= 5
    slot = (slot * 5 + perturb + 1) & mask
```

The next example runs the same recurrence in pure Python. `hash(n)` is `n` itself for
small non-negative integers, so the slots are the same on every machine. `12345` and
`12353` differ by 8, so both start in slot 1 of an 8-slot table, then split apart.
Once `perturb` reaches 0, the recurrence `slot * 5 + 1` visits every slot exactly
once, so a probe always terminates.

```python
def probe_sequence(
    hash_value: int, table_size: int, probe_count: int
) -> list[int]:
    """Return the first slots CPython's dict tries for hash_value.

    table_size must be a power of 2.
    """
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
print(
    f"{probe_sequence(hash(1), 8, 8)=}"
    "  (perturb hits 0 after one shift)"
)
```

```text
probe_sequence(hash(12345), 8, 8)=[1, 7, 0, 1, 6, 7, 4, 5]
probe_sequence(hash(12353), 8, 8)=[1, 0, 5, 2, 3, 0, 1, 6]
probe_sequence(hash(1), 8, 8)=[1, 6, 7, 4, 5, 2, 3, 0]
  (perturb hits 0 after one shift)
```

### Resizing

Probes stay short only while the table has plenty of empty slots, so CPython keeps a
dict at most about **two-thirds full**. When an insert would pass that limit, it
allocates a bigger table and re-inserts every entry. That step is O(n), but it
happens rarely enough (the table roughly doubles each time) that inserts stay O(1)
*amortized*, the same idea as `list` over-allocation in 1.5.2. You can watch
`sys.getsizeof` jump at each resize. The exact sizes vary by Python version and
platform.

```python
growing_dict: dict[int, int] = {}
previous_size = sys.getsizeof(growing_dict)
print(f"0 keys: {previous_size} bytes")
for key_count in range(1, 100):
    growing_dict[key_count] = key_count
    current_size = sys.getsizeof(growing_dict)
    if current_size != previous_size:
        print(f"{key_count:>2} keys: {current_size:>5} bytes (table resized)")
        previous_size = current_size
```

```text
0 keys: 64 bytes
 1 keys:   224 bytes (table resized)
 6 keys:   352 bytes (table resized)
11 keys:   632 bytes (table resized)
22 keys:  1168 bytes (table resized)
43 keys:  2264 bytes (table resized)
86 keys:  4688 bytes (table resized)
```

An empty dict is only 64 bytes: CPython does not allocate a table until the first
key arrives.

### Under the hood: key-sharing dicts (PEP 412)

Every instance of an ordinary class keeps its attributes in a namespace dict, and
most instances of one class have the **same attribute names**. CPython therefore
stores the keys once per class and gives each instance only its values. This is a
*split* or *key-sharing* dict (PEP 412). Recent versions go further and keep the
values inside the object itself until someone asks for `__dict__`. If you know V8,
this is the same idea as hidden classes: objects with the same shape share the
description of that shape.

`sys.getsizeof(instance.__dict__)` is misleading here, because asking for `__dict__`
materializes a dict. The next example uses `tracemalloc` instead, and measures the
memory of 10 000 objects of each kind. The exact numbers vary by version; the point
is that instances cost clearly less than plain dicts with the same three keys.

```python
class MenuItem:
    """A plain class: its instances share one key table (PEP 412)."""

    def __init__(self, name: str, price: int, is_veg: bool) -> None:
        self.name = name
        self.price = price
        self.is_veg = is_veg


def bytes_per_object(
    factory: Callable[[int], object], object_count: int = 10_000
) -> float:
    """Return the average traced memory of object_count objects."""
    tracemalloc.start()
    kept_objects = [factory(number) for number in range(object_count)]
    traced_bytes, _peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return traced_bytes / len(kept_objects)


instance_bytes = bytes_per_object(
    lambda number: MenuItem(f"dish {number}", 60, True)
)
dict_bytes = bytes_per_object(
    lambda number: {"name": f"dish {number}", "price": 60, "is_veg": True}
)
print(f"MenuItem instance: about {instance_bytes:.0f} bytes each")
print(f"plain dict:        about {dict_bytes:.0f} bytes each")
print(f"{instance_bytes < dict_bytes=}")
```

```text
MenuItem instance: about 155 bytes each
plain dict:        about 242 bytes each
instance_bytes < dict_bytes=True
```

### Dict vs list membership

`key in some_dict` hashes the key once and probes a slot or two. `value in some_list`
compares the value with every item until it finds a match. The next example searches
10 000 SKU codes for one that is missing, which is the worst case for the list.
Timings vary by machine; the ratio is what matters.

```python
sku_codes = [f"SKU{number:05}" for number in range(10_000)]
sku_lookup = dict.fromkeys(sku_codes, True)
missing_sku = "SKU-MISSING"
repeat_count = 200
list_seconds = timeit.timeit(
    lambda: missing_sku in sku_codes, number=repeat_count
)
dict_seconds = timeit.timeit(
    lambda: missing_sku in sku_lookup, number=repeat_count
)
print(
    "list membership: "
    f"{list_seconds / repeat_count * 1e6:8.2f} µs per lookup"
)
print(
    "dict membership: "
    f"{dict_seconds / repeat_count * 1e6:8.3f} µs per lookup"
)
print(
    f"dict is about {list_seconds / dict_seconds:,.0f}x faster here"
    " (varies by machine)"
)
```

```text
list membership:    53.58 µs per lookup
dict membership:    0.033 µs per lookup
dict is about 1,615x faster here (varies by machine)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Layout | Sparse indices + dense entries (3.6+) |
| Order | Insertion order is a language rule (3.7+) |
| Collisions | Open addressing, perturbed probe sequence |
| Growth | Kept ≤ 2/3 full; resize is O(n) but rare |
| Key sharing | Instances of one class share keys (PEP 412) |
| Lookup | O(1) average; a list scan is O(n) |

## 1.6.2 Hashing

### The hashing contract

`hash(obj)` returns an `int` computed by `obj.__hash__()`. An object is **hashable**
when two things hold:

1. its hash never changes during its lifetime, and
2. the hash agrees with `__eq__`: if `a == b`, then `hash(a) == hash(b)`.

The reverse is not required: two unequal objects may share a hash, which is exactly
what a collision is. Dicts and sets rely on both halves of the contract. The hash
chooses the slot, and `==` confirms that the key in the slot is the one you asked for.

Integer hashes are deterministic: `hash(n) == n` for small integers. The one oddity
is `-1`, which CPython's C code uses as an error marker, so `hash(-1)` is `-2`. Equal
tuples hash equally, because a tuple's hash is computed from its items.
`collections.abc.Hashable` tells you whether a type has a `__hash__` at all.

```python
print(f"{hash(42)=}, {hash(-1)=}, {hash(-2)=}")
print(f"{hash((1, 'dosa')) == hash((1, 'dosa'))=}")
print(f"{isinstance('dosa', Hashable)=}, {isinstance([], Hashable)=}")
```

```text
hash(42)=42, hash(-1)=-2, hash(-2)=-2
hash((1, 'dosa')) == hash((1, 'dosa'))=True
isinstance('dosa', Hashable)=True, isinstance([], Hashable)=False
```

### The contract in practice

If a class defines `__eq__` without `__hash__`, Python sets `__hash__` to `None`, and
instances become unhashable. Python refuses to guess a hash that would agree with
your idea of equality. (A class that defines neither inherits identity-based
`__eq__` and `__hash__` from `object`, which do agree.)

```python
class SkuCode:
    """Equal when the codes match; no __hash__, so it is unhashable."""

    def __init__(self, code: str) -> None:
        self.code = code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SkuCode) and self.code == other.code


print(f"{SkuCode.__hash__=}")
print(f"hash(SkuCode('A1')): {raised_error_name(lambda: hash(SkuCode('A1')))}")
```

```text
SkuCode.__hash__=None
hash(SkuCode('A1')): TypeError
```

The next class breaks the contract by hashing a field that later changes. A set
stores each element in the slot chosen by its hash *at insertion time*. After the
field changes, a lookup computes a new hash and looks in a different slot, so the set
can no longer find the object, even though it is still inside.

```python
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
```

```text
tracked_sku in tracked_skus=False  (looks in the slot for 'B2')
MutableSkuCode('A1') in tracked_skus=False  (right slot, but == fails)
len(tracked_skus)=1  (the object is still there, unreachable)
```

> **Warning:** only hash fields that never change. Phase 2 shows how frozen
> dataclasses generate a safe `__hash__` for you.

### `1`, `1.0` and `True` are one key

`True == 1 == 1.0` is true in Python (`bool` is a subclass of `int`), so the contract
*requires* `hash(True) == hash(1) == hash(1.0)`. A dict therefore treats them as the
same key. When you insert an "equal" key again, the dict keeps the **first** key
object and stores the **last** value.

```python
print(f"{hash(1) == hash(1.0) == hash(True)=}")
print(f"{1 == 1.0 == True=}")
print(f"{ {1: 'int', True: 'bool'}=}")
print(f"{len({1, 1.0, True})=}")
```

```text
hash(1) == hash(1.0) == hash(True)=True
1 == 1.0 == True=True
 {1: 'int', True: 'bool'}={1: 'bool'}
len({1, 1.0, True})=1
```

This is the mirror image of the JavaScript trap. In JS, `obj[1]` and `obj["1"]`
collide because object keys are coerced to strings. In Python, `1` and `"1"` are
different keys, but numbers that are equal collapse.

#### Predict the output: mixed numeric keys

```python
seat_labels = {1: "one", True: "yes", 1.0: "float one"}
print(seat_labels)
```

<details><summary>Answer</summary>

```text
{1: 'float one'}
```

All three keys are equal and hash the same, so they are one key. The dict keeps the
first key object (`1`) and stores each new value over the old one, so the last value
(`'float one'`) wins.

</details>

### String-hash randomization

`str` and `bytes` hashes are computed with a secret random key chosen when the
interpreter starts. Without it, an attacker who knows the hash function can send
thousands of keys that all collide (for example as form fields or JSON keys). Each
dict insert then costs O(n) instead of O(1), and a single request can tie up a
server: a **hash-flooding** denial-of-service attack, disclosed against many
languages in 2011–2012 (CVE-2012-1150 for Python). Since Python 3.4 the string hash
is **SipHash** (PEP 456), a keyed hash designed against exactly this attack:
SipHash-2-4 at first, and the faster SipHash-1-3 since 3.11.
`sys.hash_info.algorithm` names the variant.

The `PYTHONHASHSEED` environment variable controls the key. Unset or `random` means a
new key per process; an integer fixes the key, which is useful only for reproducing a
bug. The next example starts child interpreters and compares their `hash("dosa")`
values. It prints counts, never the hashes themselves, because those differ on every
run.

```python
def string_hash_in_child(hash_seed: str | None) -> str:
    """Return hash("dosa") from a fresh interpreter.

    The child runs with the given PYTHONHASHSEED (None means unset).
    """
    child_environment = {
        name: value
        for name, value in os.environ.items()
        if name != "PYTHONHASHSEED"
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
print(
    "distinct hash('dosa') values, 3 runs, random key:      "
    f"{len(random_seed_hashes)}"
)
print(
    "distinct hash('dosa') values, 3 runs, PYTHONHASHSEED=0: "
    f"{len(fixed_seed_hashes)}"
)
print(f"{sys.hash_info.algorithm=}, {sys.hash_info.width=}")
print(f"{sys.flags.hash_randomization=}")
```

```text
distinct hash('dosa') values, 3 runs, random key:      3
distinct hash('dosa') values, 3 runs, PYTHONHASHSEED=0: 1
sys.hash_info.algorithm='siphash13', sys.hash_info.width=64
sys.flags.hash_randomization=1
```

> **Warning:** never store `hash()` of a string in a file or database, or send it to
> another process. It is only meaningful inside the process that computed it. Use
> `hashlib` for stable digests.

### Unhashable types

The mutable built-ins `list`, `dict`, `set` and `bytearray` set `__hash__ = None`. A
`tuple` is hashable only if every item inside it is. This means
`isinstance(..., Hashable)` can say yes (the tuple *type* has a `__hash__`) while
`hash()` still fails for a particular tuple.

```python
print(f"list key:  {raised_error_name(lambda: {['rice']: 1})}")
print(f"dict key:  {raised_error_name(lambda: {dict(): 1})}")
print(f"set key:   {raised_error_name(lambda: {set(): 1})}")
tuple_holding_list = ("rice", [1, 2])
print(f"{isinstance(tuple_holding_list, Hashable)=}")
print(
    "hash(tuple_holding_list): "
    f"{raised_error_name(lambda: hash(tuple_holding_list))}"
)
```

```text
list key:  TypeError
dict key:  TypeError
set key:   TypeError
isinstance(tuple_holding_list, Hashable)=True
hash(tuple_holding_list): TypeError
```

### Tuple composite keys

When a record is identified by several fields, use a tuple of those fields as the
key. In JavaScript you would build a string such as `"2026-11-01|7|A"` and worry
about separators; in Python the tuple *is* the key.

```python
seat_bookings: dict[tuple[str, int, str], str] = {
    ("2026-11-01", 7, "A"): "Asha",
    ("2026-11-01", 7, "B"): "Ravi",
}
seat_bookings[("2026-11-02", 3, "A")] = "Meena"
print(f"{seat_bookings[('2026-11-01', 7, 'B')]=}")
print(f"{('2026-11-01', 7, 'C') in seat_bookings=}")
print(f"{[seat for seat in seat_bookings if seat[0] == '2026-11-01']=}")
```

```text
seat_bookings[('2026-11-01', 7, 'B')]='Ravi'
('2026-11-01', 7, 'C') in seat_bookings=False
[seat for seat in seat_bookings if seat[0] == '2026-11-01']=
  [('2026-11-01', 7, 'A'), ('2026-11-01', 7, 'B')]
```

### Collisions cost time

The next class returns the same hash for every key, so all keys land on the same
probe path. Each insert has to compare against every earlier key, and building the
dict becomes O(n²). Compare it with the same class using a proper hash: doubling the
key count should roughly double the good time but roughly quadruple the bad one.
Timings vary by machine.

```python
class ConstantHashKey:
    """A key whose hash is always 42, so every key collides."""

    def __init__(self, value: int) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ConstantHashKey) and self.value == other.value
        )

    def __hash__(self) -> int:
        return 42


class WellHashedKey(ConstantHashKey):
    """The same key with a hash that spreads values over the table."""

    def __hash__(self) -> int:
        return hash(self.value)


def build_seconds(key_class: type[ConstantHashKey], key_count: int) -> float:
    """Time building a dict of key_count keys of key_class."""
    return timeit.timeit(
        lambda: {key_class(number): number for number in range(key_count)},
        number=3,
    )


for key_count in (250, 500, 1000):
    good_seconds = build_seconds(WellHashedKey, key_count)
    bad_seconds = build_seconds(ConstantHashKey, key_count)
    print(
        f"{key_count:>5} keys: good hash {good_seconds * 1e3:6.2f} ms, "
        f"constant hash {bad_seconds * 1e3:8.2f} ms"
    )
```

```text
  250 keys: good hash   0.07 ms, constant hash     3.96 ms
  500 keys: good hash   0.22 ms, constant hash    18.79 ms
 1000 keys: good hash   0.27 ms, constant hash    71.87 ms
```

### Python has no separate "hash" type

JavaScript has `Object`, `Map` and libraries with "HashMap" classes; Java has
`HashMap` and `Hashtable`. In Python, the built-in `dict` *is* the hash map, and
`set` is the hash set. The abstract interfaces live in `collections.abc` (`Mapping`,
`MutableMapping`), and you use them in type hints when any mapping will do. A dict
itself is not hashable, which is the gap `frozendict` (1.6.5) fills.

```python
inventory = {"rice": 10}
print(f"{type(inventory).__name__=}")
print(
    f"{isinstance(inventory, Mapping)=}, "
    f"{isinstance(inventory, MutableMapping)=}"
)
print(f"{dict.__hash__ is None=}  (the hash map itself is not hashable)")
```

```text
type(inventory).__name__='dict'
isinstance(inventory, Mapping)=True, isinstance(inventory, MutableMapping)=True
dict.__hash__ is None=True  (the hash map itself is not hashable)
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Hashable | Stable `__hash__` that agrees with `__eq__` |
| `__eq__` only | Sets `__hash__ = None`: unhashable |
| `1 == 1.0 == True` | One key; first key kept, last value wins |
| String hashes | SipHash with a per-process random key |
| Unhashable | `list`, `dict`, `set`, `bytearray` |
| Composite keys | Use a tuple of the fields |
| Bad hashes | Constant hash turns O(1) into O(n) |

## 1.6.3 Dictionary methods (complete API)

This section teaches the dict API by task: access, modify, remove, views,
construction and copying. Section 1.6.9 repeats every method as a short reference.

### Access

`d[key]` raises `KeyError` for a missing key. This is the biggest day-one difference
from JavaScript, where a missing property quietly gives `undefined`. When a missing
key is normal, use `get(key, default=None)`, which never raises. The `in` operator
tests **keys**, not values. A stored `0` or `""` is a real value, so `get` returns it
rather than the default; only a *missing* key triggers the default.

```python
stock_levels = {"rice": 12, "dal": 0}
print(f"{stock_levels['rice']=}")
print(f"missing key with []: {raised_error_name(lambda: stock_levels['ghee'])}")
print(f"{stock_levels.get('ghee')=}, {stock_levels.get('ghee', 0)=}")
print(f"{stock_levels.get('dal', 99)=}  (0 is stored, so no default)")
print(f"{'dal' in stock_levels=}, {12 in stock_levels=}  (in checks keys)")
```

```text
stock_levels['rice']=12
missing key with []: KeyError
stock_levels.get('ghee')=None, stock_levels.get('ghee', 0)=0
stock_levels.get('dal', 99)=0  (0 is stored, so no default)
'dal' in stock_levels=True, 12 in stock_levels=False  (in checks keys)
```

`setdefault(key, default)` returns the value for `key`, inserting `default` first if
the key is missing. It is the one-line "get or create" used for grouping, the
equivalent of JavaScript's `(groups[k] ??= []).push(x)`.

```python
tags_by_dish: dict[str, list[str]] = {}
tags_by_dish.setdefault("dosa", []).append("veg")
tags_by_dish.setdefault("dosa", []).append("breakfast")
tags_by_dish.setdefault("kebab", []).append("grill")
print(f"{tags_by_dish=}")
print(
    f"{stock_levels.setdefault('rice', 99)=}"
    "  (existing value returned, not replaced)"
)
print(f"{stock_levels.setdefault('ghee', 3)=}, {stock_levels=}")
```

```text
tags_by_dish={'dosa': ['veg', 'breakfast'], 'kebab': ['grill']}
stock_levels.setdefault('rice', 99)=12  (existing value returned, not replaced)
stock_levels.setdefault('ghee', 3)=3,
  stock_levels={'rice': 12, 'dal': 0, 'ghee': 3}
```

> **Note:** the `default` argument is an ordinary argument, so it is evaluated on
> every call, even when the key exists. `setdefault(k, [])` builds and throws away a
> new list each time. That is cheap for `[]`, but avoid an expensive expression there;
> `defaultdict` (1.6.7) only calls its factory on a miss.

### Modify

`d[key] = value` inserts or replaces. `update` merges several pairs in place, and it
accepts a mapping, an iterable of `(key, value)` pairs, keyword arguments, or a
mapping/pairs **plus** keywords. Later values win.

```python
stock_levels = {"rice": 12}
stock_levels["dal"] = 5
stock_levels["rice"] = 10
stock_levels.update({"ghee": 2})
stock_levels.update([("salt", 7), ("tea", 3)])
stock_levels.update(sugar=4, rice=8)
stock_levels.update({"oil": 1}, oil=2)
print(f"{stock_levels=}")
```

```text
stock_levels={'rice': 8, 'dal': 5, 'ghee': 2, 'salt': 7, 'tea': 3,
  'sugar': 4, 'oil': 2}
```

The **`|` and `|=`** operators (PEP 584, Python 3.9) are the Python spelling of
object spread. `a | b` builds a new dict and needs a dict on both sides; `a |= b`
updates `a` in place and, like `update`, also accepts pairs. On duplicate keys the
right side wins, just as `{...a, ...b}` does in JavaScript.

```python
default_settings = {"theme": "light", "page_size": 20}
user_settings = {"page_size": 50}
merged_settings = default_settings | user_settings
print(f"{merged_settings=}")
print(f"{default_settings=}  (unchanged by |)")
default_settings |= [("language", "en")]
print(f"{default_settings=}  (|= accepts pairs)")
print(
    "dict | list: "
    f"{raised_error_name(lambda: default_settings | [('x', 1)])}"
)
```

```text
merged_settings={'theme': 'light', 'page_size': 50}
default_settings={'theme': 'light', 'page_size': 20}  (unchanged by |)
default_settings={'theme': 'light', 'page_size': 20, 'language': 'en'}
  (|= accepts pairs)
dict | list: TypeError
```

### Remove

- `pop(key, default)` removes the key and returns its value; without a default, a
  missing key raises `KeyError`.
- `popitem()` removes and returns the **last inserted** pair, so a dict can act as a
  LIFO stack of pairs.
- `del d[key]` is a statement that removes a key, raising `KeyError` if it is missing.
- `clear()` empties the dict in place, so every alias sees the empty dict.

`del` is a statement, not an expression, so it cannot appear inside a `lambda`. The
small helper `delete_key` wraps it so the example can show the error.

```python
def delete_key(mapping: dict[str, int], key: str) -> None:
    """Run del mapping[key] (del is a statement, so not usable in a lambda)."""
    del mapping[key]


shopping_basket = {"rice": 2, "dal": 1, "ghee": 1}
print(
    f"{shopping_basket.pop('dal')=}, "
    f"{shopping_basket.pop('salt', 0)=}"
)
print(
    "pop missing, no default: "
    f"{raised_error_name(lambda: shopping_basket.pop('salt'))}"
)
shopping_basket["tea"] = 3
print(f"{shopping_basket.popitem()=}  (the last inserted pair)")
delete_key(shopping_basket, "rice")
print(f"{shopping_basket=}")
print(
    "del missing key: "
    f"{raised_error_name(lambda: delete_key(shopping_basket, 'oil'))}"
)
shopping_basket.clear()
print(
    f"{shopping_basket=}, popitem on empty: "
    f"{raised_error_name(shopping_basket.popitem)}"
)
```

```text
shopping_basket.pop('dal')=1, shopping_basket.pop('salt', 0)=0
pop missing, no default: KeyError
shopping_basket.popitem()=('tea', 3)  (the last inserted pair)
shopping_basket={'ghee': 1}
del missing key: KeyError
shopping_basket={}, popitem on empty: KeyError
```

### Views

`keys()`, `values()` and `items()` do not copy anything. They return **views**: small
objects that read the dict live, so later changes show through. This differs from
JavaScript, where `Object.keys(obj)` returns a fresh array snapshot. Wrap a view in
`list()` when you need a snapshot.

```python
menu_prices = {"dosa": 60, "idli": 40}
menu_keys = menu_prices.keys()
menu_items = menu_prices.items()
menu_prices["vada"] = 30
print(f"{menu_keys=}")
print(f"{menu_items=}")
print(f"{list(menu_prices.values())=}, {('idli', 40) in menu_items=}")
```

```text
menu_keys=dict_keys(['dosa', 'idli', 'vada'])
menu_items=dict_items([('dosa', 60), ('idli', 40), ('vada', 30)])
list(menu_prices.values())=[60, 40, 30], ('idli', 40) in menu_items=True
```

Key and item views also behave like sets: `&`, `|`, `-` and `^` work on them and
return real `set` objects, and the right operand can be any iterable. Value views do
not support this, because values need not be hashable or unique. The results below
are sets of strings, so they are printed sorted.

```python
store_a_stock = {"rice": 12, "dal": 5, "ghee": 2}
store_b_stock = {"dal": 3, "salt": 9}
print(f"{sorted(store_a_stock.keys() & store_b_stock.keys())=}")
print(f"{sorted(store_a_stock.keys() - store_b_stock.keys())=}")
print(f"{sorted(store_a_stock.keys() | store_b_stock.keys())=}")
print(f"{sorted(store_a_stock.keys() ^ store_b_stock.keys())=}")
print(
    f"{sorted(store_a_stock.keys() & ['dal', 'oil'])=}"
    "  (any iterable on the right)"
)
print(
    "values() & ...: "
    f"{raised_error_name(lambda: store_a_stock.values() & {5})}"
)
```

```text
sorted(store_a_stock.keys() & store_b_stock.keys())=['dal']
sorted(store_a_stock.keys() - store_b_stock.keys())=['ghee', 'rice']
sorted(store_a_stock.keys() | store_b_stock.keys())=
  ['dal', 'ghee', 'rice', 'salt']
sorted(store_a_stock.keys() ^ store_b_stock.keys())=['ghee', 'rice', 'salt']
sorted(store_a_stock.keys() & ['dal', 'oil'])=['dal']
  (any iterable on the right)
values() & ...: TypeError
```

### Construction

There are five equivalent ways to build the same dict: a literal, keyword arguments,
a list of pairs, `zip` of two lists, and a dict comprehension. `dict.fromkeys` gives
every key the same value. When zipping keys and values, pass `strict=True` so that
lists of different lengths raise `ValueError` instead of silently dropping items.

```python
from_literal = {"dosa": 60, "idli": 40}
from_keywords = dict(dosa=60, idli=40)
from_pairs = dict([("dosa", 60), ("idli", 40)])
from_zip = dict(zip(["dosa", "idli"], [60, 40], strict=True))
from_comprehension = {
    dish: price for dish, price in [("dosa", 60), ("idli", 40)]
}
all_five_equal = (
    from_literal
    == from_keywords
    == from_pairs
    == from_zip
    == from_comprehension
)
print(f"{all_five_equal=}")
print(f"{dict.fromkeys(['dosa', 'idli'], 0)=}")
mismatched_zip = raised_error_name(
    lambda: dict(zip(["dosa"], [60, 40], strict=True))
)
print(f"zip with different lengths: {mismatched_zip}")
```

```text
all_five_equal=True
dict.fromkeys(['dosa', 'idli'], 0)={'dosa': 0, 'idli': 0}
zip with different lengths: ValueError
```

#### Predict the output: the `dict.fromkeys` shared-value trap

```python
orders_by_table = dict.fromkeys(["T1", "T2"], [])
orders_by_table["T1"].append("dosa")
print(orders_by_table)
```

<details><summary>Answer</summary>

```text
{'T1': ['dosa'], 'T2': ['dosa']}
```

`fromkeys` evaluates `[]` **once** and stores that same list object under every
key, so appending through one key shows under all of them. It is the dict version of
`[[0] * 3] * 3` from Lab 1.5. You can confirm it with `is`:

```python
print(f"{orders_by_table['T1'] is orders_by_table['T2']=}")
```

```text
orders_by_table['T1'] is orders_by_table['T2']=True
```

</details>

The fix is a comprehension, which evaluates `[]` once **per key**. `dict.fromkeys` is
still fine with immutable values such as `0`, `None` or `False`.

```python
orders_by_table = {table: [] for table in ["T1", "T2"]}
orders_by_table["T1"].append("dosa")
print(f"{orders_by_table=}")
```

```text
orders_by_table={'T1': ['dosa'], 'T2': []}
```

### Copying

`copy()` and `{**d}` both make a **shallow** copy: a new outer dict whose values are
the same objects as in the original. Rebinding a key in the copy is independent of the
original; mutating a shared inner list is not. Unit 1.7 covers deep copies.

```python
dosa_recipe = {"ingredients": ["rice", "urad dal"], "price": 60}
copied_recipe = dosa_recipe.copy()
unpacked_recipe = {**dosa_recipe, "price": 65}
copied_recipe["price"] = 70  # rebinding: only the copy changes
copied_recipe["ingredients"].append("salt")  # mutating a shared list
print(f"{dosa_recipe=}")
print(f"{unpacked_recipe=}")
print(f"{copied_recipe['ingredients'] is dosa_recipe['ingredients']=}")
```

```text
dosa_recipe={'ingredients': ['rice', 'urad dal', 'salt'], 'price': 60}
unpacked_recipe={'ingredients': ['rice', 'urad dal', 'salt'], 'price': 65}
copied_recipe['ingredients'] is dosa_recipe['ingredients']=True
```

### Changing size during iteration

Adding or deleting keys while a `for` loop walks the dict could trigger a resize and
make the loop skip or repeat entries. CPython detects the size change and raises
`RuntimeError` instead. (JavaScript silently allows `delete` inside `for...in`.)
Replacing values is allowed, because it does not change the layout. To delete while
looping, iterate over a snapshot of the keys (`list(d)`) or build a new dict.

```python
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
```

```text
RuntimeError: dictionary changed size during iteration
stock_levels={'rice': 13, 'salt': 8}
```

Notice that the first loop had already deleted `"dal"` when the error was raised:
the size check happens on the *next* step of the iteration, so work done before it is
not undone. The second loop then turns `"ghee"` into `1`, and the snapshot loop
deletes it safely.

### Key points

| Task | Use |
| --- | --- |
| Read, may be missing | `d.get(key, default)` |
| Get or create | `d.setdefault(key, [])` |
| Merge | `a \| b` (new) or `a \|= b` (in place) |
| Remove | `pop`, `popitem` (LIFO), `del`, `clear` |
| Live keys/items | Views; set operators on keys and items |
| Same mutable value per key | Comprehension, never `fromkeys` |
| Delete while looping | Loop over `list(d)` |

## 1.6.4 dict vs JS objects

A Python `dict` behaves much more like a JavaScript `Map` than like a plain object.
There is no prototype chain, no key coercion, and no dot access.

| Feature | JS `Object` | JS `Map` | Python `dict` |
| --- | --- | --- | --- |
| Key types | strings, symbols | any value | any hashable |
| Coercion | `1` → `"1"` | none | none (`1 == 1.0` merge) |
| Inherited keys | yes (prototype) | none | none |
| Order | int-like keys first | insertion | insertion (3.7+) |
| Size | `Object.keys(o).length` | `m.size` | `len(d)` |
| Missing key | `undefined` | `undefined` | `KeyError` / `get` |
| Dot access | `o.name` | no | no |
| JSON | native | convert first | `json.dumps(d)` |

A few of these rows deserve a sentence. In JavaScript, `"toString" in {}` is `true`
because the key is inherited from `Object.prototype`; in Python, methods are
*attributes* of the dict object, never keys, so an empty dict really is empty. A JS
object lists integer-like keys first in ascending order, then the other strings in
insertion order; a Python dict always uses plain insertion order. JSON
serialization needs string keys, which 1.6.12 covers. The next example checks the
Python column.

```python
mixed_keys = {1: "int one", "1": "string one", (2, 3): "tuple key"}
print(f"{len(mixed_keys)=}, {mixed_keys[1]=}, {mixed_keys['1']=}")
empty_dict: dict[str, int] = {}
print(
    f"{'keys' in empty_dict=}, {'__init__' in empty_dict=}"
    "  (methods are not keys)"
)
insertion_ordered = {"b": 1, 10: 2, "a": 3, 2: 4}
print(f"{list(insertion_ordered)=}  (JS would list 2 and 10 first)")
print(f"missing key: {raised_error_name(lambda: empty_dict['name'])}")
```

```text
len(mixed_keys)=3, mixed_keys[1]='int one', mixed_keys['1']='string one'
'keys' in empty_dict=False, '__init__' in empty_dict=False
  (methods are not keys)
list(insertion_ordered)=['b', 10, 'a', 2]  (JS would list 2 and 10 first)
missing key: KeyError
```

### `types.SimpleNamespace` for attribute access

If you miss writing `config.port`, `types.SimpleNamespace` gives attribute access
over a plain `__dict__`. It supports `==`, has a readable `repr`, and lets you add
attributes later; a missing attribute raises `AttributeError`. *New in 3.13:* it also
accepts a mapping or an iterable of pairs as a positional argument, which is handy
for parsed JSON. For anything with a fixed set of fields, a class or a `NamedTuple`
is usually better, because the fields are then documented and type-checked.

```python
app_config = types.SimpleNamespace(debug=False, port=8000)
app_config.port = 8080
app_config.log_level = "INFO"
print(f"{app_config=}")
print(f"{app_config.port=}, {vars(app_config)=}")
print(f"missing attribute: {raised_error_name(lambda: app_config.timeout)}")
if sys.version_info >= (3, 13):
    parsed_config = types.SimpleNamespace(
        json.loads('{"host": "localhost"}'), port=5432
    )
    print(f"{parsed_config=}")
else:
    print("SimpleNamespace(mapping) needs Python 3.13+; skipped")
```

```text
app_config=namespace(debug=False, port=8080, log_level='INFO')
app_config.port=8080,
  vars(app_config)={'debug': False, 'port': 8080, 'log_level': 'INFO'}
missing attribute: AttributeError
parsed_config=namespace(host='localhost', port=5432)
```

### Key points

| JavaScript habit | Python reality |
| --- | --- |
| `obj.key` | `d["key"]`, or `SimpleNamespace` |
| Missing key is `undefined` | `KeyError`; use `get` |
| Keys coerced to strings | Keys keep their type |
| Inherited prototype keys | None; methods are not keys |
| Int-like keys sorted first | Pure insertion order |

## 1.6.5 Immutable mappings

### `frozendict` (new in 3.15)

JavaScript's `Object.freeze` makes an object read-only, but the frozen object still
cannot be used as a `Map` key by value. Python 3.15 adds a built-in **`frozendict`**
(PEP 814): an immutable dict that is **hashable** when all its values are. That means
it can be a dict key, a set member, or a module-level constant that nobody can
change by accident.

It supports the read-only dict API (`[]`, `get`, `keys`, `values`, `items`, `copy`,
`fromkeys`, `in`, `len`, `==`). `|` returns a **new** `frozendict`, leaving the
original alone. A `frozendict` compares equal to a `dict` with the same pairs, and two
frozendicts with the same pairs in a different order are equal and hash equally.

Assignment cannot go in a `lambda`, so the small helper `try_assign` wraps it. The
example is guarded by a version check so that it still runs (and explains itself) on
older interpreters.

```python
def try_assign(mapping: Any, key: str, value: object) -> None:
    """Run mapping[key] = value (assignment cannot go in a lambda)."""
    mapping[key] = value


if sys.version_info >= (3, 15):
    GST_RATES = frozendict(food=5, electronics=18, luxury=28)
    print(f"{GST_RATES=}, {GST_RATES['food']=}")
    assignment_result = raised_error_name(
        lambda: try_assign(GST_RATES, "food", 0)
    )
    print(f"item assignment: {assignment_result}")
    rates_with_services = GST_RATES | {"services": 18}
    print(
        f"{type(rates_with_services).__name__=}, "
        f"{len(rates_with_services)=}, {len(GST_RATES)=}"
    )
    rate_table_years = {GST_RATES: "FY2026"}  # hashable, so usable as a key
    print(
        f"{rate_table_years[frozendict(luxury=28, food=5, electronics=18)]=}"
    )
    print(f"{GST_RATES == {'food': 5, 'electronics': 18, 'luxury': 28}=}")
    unhashable_result = raised_error_name(
        lambda: hash(frozendict(tags=["veg"]))
    )
    print(f"unhashable value: {unhashable_result}")
else:
    print("frozendict is new in Python 3.15; the demo is skipped")
```

```text
GST_RATES=frozendict({'food': 5, 'electronics': 18, 'luxury': 28}),
  GST_RATES['food']=5
item assignment: TypeError
type(rates_with_services).__name__='frozendict', len(rates_with_services)=4,
  len(GST_RATES)=3
rate_table_years[frozendict(luxury=28, food=5, electronics=18)]='FY2026'
GST_RATES == {'food': 5, 'electronics': 18, 'luxury': 28}=True
unhashable value: TypeError
```

> **Note:** a `frozendict` is shallowly immutable, like a tuple. If a value is a list,
> the list can still change, and the frozendict is then unhashable (the last line
> above).

### `types.MappingProxyType`: a read-only live view

`types.MappingProxyType` wraps an existing dict in a read-only **live view**. You
cannot write through the proxy, but changes made to the underlying dict show through.
CPython uses it to expose class namespaces (`SomeClass.__dict__` is a
`mappingproxy`), and a module can use it to hand out its settings without letting
callers change them. It is not a snapshot, and it is hashable only if the wrapped
mapping is (a dict is not).

| | `dict` | `frozendict` | `MappingProxyType` |
| --- | --- | --- | --- |
| Writable | yes | no | no (via proxy) |
| Sees later changes | — | no (owns data) | yes (live) |
| Hashable | no | if values are | no |
| Available | always | 3.15+ | 3.3+ |

```python
_settings_store = {"currency": "INR", "tax_rate": 18}
SETTINGS_VIEW = types.MappingProxyType(_settings_store)
print(f"{SETTINGS_VIEW['currency']=}")
write_result = raised_error_name(
    lambda: try_assign(SETTINGS_VIEW, "currency", "USD")
)
print(f"write through the proxy: {write_result}")
_settings_store["tax_rate"] = 12
print(f"{SETTINGS_VIEW['tax_rate']=}  (live: sees the change)")
print(f"hash(SETTINGS_VIEW): {raised_error_name(lambda: hash(SETTINGS_VIEW))}")
print(
    f"{type(int.__dict__).__name__=}"
    "  (class namespaces are exposed this way)"
)
```

```text
SETTINGS_VIEW['currency']='INR'
write through the proxy: TypeError
SETTINGS_VIEW['tax_rate']=12  (live: sees the change)
hash(SETTINGS_VIEW): TypeError
type(int.__dict__).__name__='mappingproxy'
  (class namespaces are exposed this way)
```

### Key points

| Need | Use |
| --- | --- |
| Constant table, usable as a key | `frozendict` (3.15+) |
| Read-only window onto live data | `MappingProxyType` |
| Derive a changed constant | `frozen \| {...}` (new object) |
| Hashable | `frozendict`, if all values are |

## 1.6.6 Sets (`set`) and frozen sets (`frozenset`)

A `set` is a hash table of keys with no values. It follows the same hashing rules as
dict keys, gives O(1) average `in`, holds no duplicates, and makes **no order
guarantee**: unlike a dict, a set does not remember insertion order. Python had dicts
long before sets, so `{}` is an empty **dict**; an empty set is written `set()`.

```python
empty_braces = {}
empty_set = set()
print(f"{type(empty_braces).__name__=}, {type(empty_set).__name__=}")
visited_cities = {"Pune", "Delhi", "Pune", "Goa"}
print(f"{sorted(visited_cities)=}, {len(visited_cities)=}")
print(f"{sorted(set('banana'))=}  (a str is an iterable of characters)")
print(f"list as an element: {raised_error_name(lambda: {['Pune']})}")
```

```text
type(empty_braces).__name__='dict', type(empty_set).__name__='set'
sorted(visited_cities)=['Delhi', 'Goa', 'Pune'], len(visited_cities)=3
sorted(set('banana'))=['a', 'b', 'n']  (a str is an iterable of characters)
list as an element: TypeError
```

### Adding and removing

`add(x)` adds one element; `update(*iterables)` adds every element of each iterable.
`remove(x)` raises `KeyError` if `x` is missing, while `discard(x)` does nothing:
choose `remove` when a missing element would be a bug, `discard` when it is fine.
`pop()` removes and returns an **arbitrary** element, so the example only checks that
it came from the set. `clear()` empties the set.

```python
user_roles = {"viewer"}
user_roles.add("editor")
user_roles.add("viewer")  # already present: no change
user_roles.update(["admin", "auditor"], ("editor",))
print(f"{sorted(user_roles)=}")
user_roles.discard("guest")  # absent: silently ignored
print(f"remove absent: {raised_error_name(lambda: user_roles.remove('guest'))}")
user_roles.remove("auditor")
popped_role = user_roles.pop()
print(
    f"{popped_role in {'viewer', 'editor', 'admin'}=}, "
    f"{len(user_roles)=}"
)
user_roles.clear()
print(f"{user_roles=}")
```

```text
sorted(user_roles)=['admin', 'auditor', 'editor', 'viewer']
remove absent: KeyError
popped_role in {'viewer', 'editor', 'admin'}=True, len(user_roles)=2
user_roles=set()
```

### Operators vs methods

`|` is union, `&` intersection, `-` difference and `^` symmetric difference. The
named methods (`union`, `intersection`, `difference`, `symmetric_difference`) do the
same, but they accept **any iterables**, several at once; the operators require sets
(or frozensets) on both sides. JavaScript gained similar methods on `Set` in ES2025,
but has no operators for them.

```python
python_developers = {"asha", "ravi", "meena"}
javascript_developers = {"ravi", "john", "meena"}
print(f"{sorted(python_developers | javascript_developers)=}")
print(f"{sorted(python_developers & javascript_developers)=}")
print(f"{sorted(python_developers - javascript_developers)=}")
print(f"{sorted(python_developers ^ javascript_developers)=}")
print(f"{sorted(python_developers.union(['zoe'], ('kim',)))=}")
print(f"{sorted(python_developers.intersection(['ravi', 'kim']))=}")
print(f"set | list: {raised_error_name(lambda: python_developers | ['zoe'])}")
```

```text
sorted(python_developers | javascript_developers)=
  ['asha', 'john', 'meena', 'ravi']
sorted(python_developers & javascript_developers)=['meena', 'ravi']
sorted(python_developers - javascript_developers)=['asha']
sorted(python_developers ^ javascript_developers)=['asha', 'john']
sorted(python_developers.union(['zoe'], ('kim',)))=
  ['asha', 'kim', 'meena', 'ravi', 'zoe']
sorted(python_developers.intersection(['ravi', 'kim']))=['ravi']
set | list: TypeError
```

### Relations

`issubset` (`<=`), `issuperset` (`>=`) and `isdisjoint` (no common elements) compare
whole sets. `<` and `>` test *proper* subsets and supersets: a subset that is not
equal.

```python
required_permissions = {"read", "write"}
granted_permissions = {"read", "write", "delete"}
print(f"{required_permissions.issubset(granted_permissions)=}")
print(f"{granted_permissions.issuperset(required_permissions)=}")
print(f"{required_permissions < granted_permissions=}  (proper subset)")
print(
    f"{required_permissions < required_permissions=}"
    "  (equal is not proper)"
)
print(f"{required_permissions.isdisjoint({'admin', 'billing'})=}")
```

```text
required_permissions.issubset(granted_permissions)=True
granted_permissions.issuperset(required_permissions)=True
required_permissions < granted_permissions=True  (proper subset)
required_permissions < required_permissions=False  (equal is not proper)
required_permissions.isdisjoint({'admin', 'billing'})=True
```

### In-place variants

`|=`, `&=`, `-=` and `^=` (and the methods `update`, `intersection_update`,
`difference_update`, `symmetric_difference_update`) change the set itself instead of
building a new one, so every alias sees the change. A plain `a = a | b` builds a new
set and rebinds the name, leaving aliases pointing at the old one.

```python
active_users = {"asha", "ravi"}
same_set_alias = active_users
active_users |= {"meena"}
active_users -= {"ravi"}
active_users &= {"asha", "meena", "john"}
active_users ^= {"john"}
print(f"{sorted(active_users)=}, {active_users is same_set_alias=}")
active_users = active_users | {"kim"}  # plain | rebinds to a new set
print(f"{active_users is same_set_alias=}")
```

```text
sorted(active_users)=['asha', 'john', 'meena'],
  active_users is same_set_alias=True
active_users is same_set_alias=False
```

### Set comprehensions

A set comprehension uses braces with a single expression (no `key: value`). It is the
idiomatic way to normalise and deduplicate in one step.

```python
raw_emails = ["Asha@Example.com", "ravi@example.com ", "asha@example.com"]
unique_domains = {email.strip().lower().split("@")[1] for email in raw_emails}
unique_emails = {email.strip().lower() for email in raw_emails}
print(f"{unique_domains=}")
print(f"{sorted(unique_emails)=}")
```

```text
unique_domains={'example.com'}
sorted(unique_emails)=['asha@example.com', 'ravi@example.com']
```

### `frozenset` as a dict key

**`frozenset`** is the immutable, hashable set. Use it where a set must itself be a
dict key or a set member. Here it models an undirected route, where
`{"Pune", "Mumbai"}` and `{"Mumbai", "Pune"}` must be the same key.

```python
route_distances_km = {
    frozenset({"Pune", "Mumbai"}): 150,
    frozenset({"Delhi", "Agra"}): 230,
}
print(
    f"{route_distances_km[frozenset({'Mumbai', 'Pune'})]=}"
    "  (order does not matter)"
)
set_as_key_result = raised_error_name(lambda: {set(["Pune"]): 1})
print(f"plain set as a key: {set_as_key_result}")
```

```text
route_distances_km[frozenset({'Mumbai', 'Pune'})]=150  (order does not matter)
plain set as a key: TypeError
```

### Key points

| Idea | Takeaway |
| --- | --- |
| Empty set | `set()`; `{}` is a dict |
| Order | None guaranteed; sort before printing |
| `remove` vs `discard` | Raises vs silent on a missing element |
| Operators vs methods | Operators need sets; methods take iterables |
| `<` vs `<=` | Proper subset vs subset |
| In place | `\|=` etc. mutate; aliases see it |
| Hashable set | `frozenset` |

## 1.6.7 The `collections` module

The built-in `dict`, `list` and `set` cover most needs. The standard-library
`collections` module adds five specialised containers for the cases they handle
badly: queues, counting, grouping, reorderable mappings and layered lookups.
Section 1.6.11 lists every method again with one example each.

### `deque`: double-ended queue

A `deque` (pronounced "deck") is a doubly linked list of fixed-size blocks, each
holding 64 item pointers. Adding or removing at **either** end touches only the
block at that end, so `append`, `appendleft`, `pop` and `popleft` are all O(1). A
`list` is fast only at the right end. `extendleft` adds items one at a time to the
front, so their order flips.

```python
print_queue = deque(["report.pdf"])
print_queue.append("invoice.pdf")
print_queue.appendleft("urgent.pdf")
print(f"{print_queue=}")
print(f"{print_queue.popleft()=}, {print_queue.pop()=}, {print_queue=}")
print_queue.extendleft(["b.pdf", "a.pdf"])
print(f"{print_queue=}  (extendleft reversed the order)")
```

```text
print_queue=deque(['urgent.pdf', 'report.pdf', 'invoice.pdf'])
print_queue.popleft()='urgent.pdf', print_queue.pop()='invoice.pdf',
  print_queue=deque(['report.pdf'])
print_queue=deque(['a.pdf', 'b.pdf', 'report.pdf'])
  (extendleft reversed the order)
```

`rotate(n)` moves `n` items from the right end to the left; a negative `n` goes the
other way. That is a round-robin in one call.

```python
server_pool = deque(["server-a", "server-b", "server-c"])
server_pool.rotate(1)
print(f"after rotate(1):  {list(server_pool)}")
server_pool.rotate(-2)
print(f"after rotate(-2): {list(server_pool)}")
```

```text
after rotate(1):  ['server-c', 'server-a', 'server-b']
after rotate(-2): ['server-b', 'server-c', 'server-a']
```

`maxlen` turns a deque into a **ring buffer**: once it is full, each append silently
drops an item from the other end. It is the natural container for "the last N
readings".

```python
recent_temperatures: deque[float] = deque(maxlen=3)
for reading in [21.5, 22.0, 22.4, 23.1, 22.8]:
    recent_temperatures.append(reading)
    print(f"after {reading}: {list(recent_temperatures)}")
print(f"{recent_temperatures.maxlen=}")
```

```text
after 21.5: [21.5]
after 22.0: [21.5, 22.0]
after 22.4: [21.5, 22.0, 22.4]
after 23.1: [22.0, 22.4, 23.1]
after 22.8: [22.4, 23.1, 22.8]
recent_temperatures.maxlen=3
```

**Benchmark: `deque.popleft()` vs `list.pop(0)`.** A list stores its items in one
contiguous array of pointers, so removing index 0 shifts every remaining pointer
left: O(n) per pop, and O(n²) to drain the whole queue. JavaScript's
`Array.prototype.shift` has the same problem. On a deque each pop is O(1). Tripling
the size should roughly triple the deque time and multiply the list time by about
nine. Timings vary by machine.

```python
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
    print(
        f"{item_count:>6} items: list.pop(0) {list_ms:8.2f} ms, "
        f"popleft() {deque_ms:6.2f} ms"
    )
```

```text
 10000 items: list.pop(0)     5.22 ms, popleft()   0.23 ms
 30000 items: list.pop(0)    54.86 ms, popleft()   0.80 ms
```

> **Note:** indexing into the middle of a deque (`queue[500]`) is O(n), because it
> has to walk the blocks. Use a deque for its ends, a list for random access.

### `Counter`: a dict of counts

`Counter(iterable)` counts hashable items. It is a `dict` subclass that maps
item → count, so everything you know about dicts still applies.

- `most_common(n)` returns the top `n` pairs; ties keep first-seen order.
- `update` **adds** counts (unlike `dict.update`, which replaces values).
- `subtract` removes counts in place; counts may go to zero or below.
- `total()` sums the counts (3.10+).
- `elements()` repeats each item by its count.

```python
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
```

```text
dish_counts=Counter({'dosa': 3, 'idli': 2, 'vada': 1})
dish_counts.most_common(2)=[('dosa', 3), ('idli', 2)]
dish_counts=Counter({'dosa': 5, 'vada': 3, 'idli': -1})  (idli went negative)
dish_counts.total()=7
list(Counter(dosa=2, vada=1).elements())=['dosa', 'dosa', 'vada']
```

**Counter arithmetic.** Counters behave like multisets. `+` adds counts; `-`
subtracts and **drops** zero and negative results; `&` keeps the minimum of each
count; `|` keeps the maximum.

```python
morning_sales = Counter(dosa=5, idli=3, vada=1)
evening_sales = Counter(dosa=2, vada=4)
print(f"{morning_sales + evening_sales=}")
print(f"{morning_sales - evening_sales=}  (vada 1 - 4 dropped)")
print(f"{morning_sales & evening_sales=}  (minimum)")
print(f"{morning_sales | evening_sales=}  (maximum)")
```

```text
morning_sales + evening_sales=Counter({'dosa': 7, 'vada': 5, 'idli': 3})
morning_sales - evening_sales=Counter({'dosa': 3, 'idli': 3})
  (vada 1 - 4 dropped)
morning_sales & evening_sales=Counter({'dosa': 2, 'vada': 1})  (minimum)
morning_sales | evening_sales=Counter({'dosa': 5, 'vada': 4, 'idli': 3})
  (maximum)
```

> **Warning:** `subtract()` keeps negative counts, but the `-` operator drops them.
> Pick the one that matches what a negative count means in your data.

### `defaultdict`: a dict that creates missing values

`defaultdict(factory)` calls `factory()` to create a value whenever a **missing key
is read** with `[]`, stores that value, and returns it. The factory is any
zero-argument callable (`list`, `int`, `set`, a lambda) and is kept in the
`default_factory` attribute. This removes the "does the key exist yet?" check from
every grouping loop.

```python
dishes_by_customer: defaultdict[str, list[str]] = defaultdict(list)
for customer_name, dish in [
    ("asha", "dosa"),
    ("ravi", "idli"),
    ("asha", "vada"),
]:
    dishes_by_customer[customer_name].append(dish)
print(f"{dict(dishes_by_customer)=}")
print(f"{dishes_by_customer.default_factory=}")
print(f"{dishes_by_customer['zoe']=}  (a read created the key)")
print(f"{'zoe' in dishes_by_customer=}")
```

```text
dict(dishes_by_customer)={'asha': ['dosa', 'vada'], 'ravi': ['idli']}
dishes_by_customer.default_factory=<class 'list'>
dishes_by_customer['zoe']=[]  (a read created the key)
'zoe' in dishes_by_customer=True
```

> **Warning:** reading a key you did not mean to create still inserts it. Test with
> `in` or `get` when you only want to look, and convert to a plain `dict` before
> returning the result from a function.

**Nested defaultdicts.** The factory can itself build a defaultdict, which gives
two-level counting without any checks for whether the inner dict exists yet. A
function that returns `defaultdict(itself)` builds an auto-vivifying tree of any
depth. A defaultdict is a dict, so `json.dumps` serializes it directly.

```python
sales_by_city_and_dish: defaultdict[str, defaultdict[str, int]] = (
    defaultdict(lambda: defaultdict(int))
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
```

```text
{"Goa": {"dosa": 2}, "Pune": {"dosa": 3, "idli": 1}}
{"shop": {"cart": {"checkout": "checkout.html"}}}
```

**The `__missing__` hook.** When `dict.__getitem__` cannot find a key, it checks
whether the dict's class defines `__missing__(key)`, and if so returns whatever that
method returns. `defaultdict` is just a dict whose `__missing__` calls the factory and
stores the result. Writing your own `__missing__` lets you choose the behaviour: the
class below returns `0` **without** inserting anything. Only `d[key]` triggers the
hook; `get()` and `in` never call `__missing__`.

```python
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
```

```text
stock_counts['rice']=5
  __missing__('ghee') called
stock_counts['ghee']=0
stock_counts.get('ghee')=None  (get does not call __missing__)
'ghee' in stock_counts=False  (nothing was inserted)
```

### `OrderedDict`: order you can rearrange

Plain dicts have kept insertion order since 3.7, so `OrderedDict` is now for the
things a dict cannot do:

- `move_to_end(key, last=True)` moves a key to the end, or to the front with
  `last=False`;
- `popitem(last=False)` removes the **oldest** item (a plain dict's `popitem` only
  removes the newest);
- equality between two `OrderedDict`s is **order-sensitive**.

Those first two operations are exactly what an LRU cache needs (Lab 1.6). Under the
hood, an `OrderedDict` adds a doubly linked list of keys on top of the hash table,
which is why moving a key is O(1).

```python
recently_viewed = OrderedDict.fromkeys(["home", "cart", "checkout"])
recently_viewed.move_to_end("home")
print(f"{list(recently_viewed)=}")
recently_viewed.move_to_end("checkout", last=False)
print(f"{list(recently_viewed)=}")
print(f"{recently_viewed.popitem(last=False)=}  (oldest first)")
print(f"{OrderedDict(a=1, b=2) == OrderedDict(b=2, a=1)=}")
print(f"{dict(a=1, b=2) == dict(b=2, a=1)=}")
print(
    f"{OrderedDict(a=1, b=2) == {'b': 2, 'a': 1}=}"
    "  (vs a dict: order ignored)"
)
```

```text
list(recently_viewed)=['cart', 'checkout', 'home']
list(recently_viewed)=['checkout', 'cart', 'home']
recently_viewed.popitem(last=False)=('checkout', None)  (oldest first)
OrderedDict(a=1, b=2) == OrderedDict(b=2, a=1)=False
dict(a=1, b=2) == dict(b=2, a=1)=True
OrderedDict(a=1, b=2) == {'b': 2, 'a': 1}=True  (vs a dict: order ignored)
```

### `ChainMap`: layered lookups

`ChainMap(first, second, ...)` searches several mappings in order **without copying
them**. The first mapping that has the key wins. The typical use is configuration
layers such as command line > environment > defaults. Writes and deletes affect only
the first mapping. Compare JavaScript's `Object.assign({}, defaults, env, cli)`,
which copies everything into a new object and loses track of where each value came
from.

```python
default_settings = {"host": "localhost", "port": 8000, "debug": False}
environment_settings = {"port": 9000}
command_line_settings = {"debug": True}
effective_settings = ChainMap(
    command_line_settings, environment_settings, default_settings
)
print(f"{effective_settings['port']=}, {effective_settings['debug']=}")
print(f"{effective_settings['host']=}  (only the defaults have it)")
print(f"{dict(effective_settings)=}")
effective_settings["port"] = 7000
print(f"{command_line_settings=}, {environment_settings=}")
```

```text
effective_settings['port']=9000, effective_settings['debug']=True
effective_settings['host']='localhost'  (only the defaults have it)
dict(effective_settings)={'host': 'localhost', 'port': 9000, 'debug': True}
command_line_settings={'debug': True, 'port': 7000},
  environment_settings={'port': 9000}
```

### Key points

| Type | Reach for it when |
| --- | --- |
| `deque` | Queues, both ends, last-N buffers |
| `Counter` | Counting; top-k; multiset maths |
| `defaultdict` | Grouping; nested accumulation |
| `OrderedDict` | Reordering; oldest-first eviction |
| `ChainMap` | Layered lookups without copying |

## 1.6.8 Choosing a container

With this unit and Unit 1.5 you have met every core container. The three tables
below compare them; read them together, row by row.

| Container | Ordered | Mutable | Duplicates |
| --- | --- | --- | --- |
| `list` | yes | yes | yes |
| `tuple` | yes | no | yes |
| `NamedTuple` | yes | no | yes |
| `dict` | insertion | yes | unique keys |
| `set` | no | yes | no |
| `frozenset` | no | no | no |
| `deque` | yes | yes | yes |
| `Counter` | insertion | yes | counts |
| `defaultdict` | insertion | yes | unique keys |
| `frozendict` | insertion | no | unique keys |
| `array.array` | yes | yes | yes |

| Container | Hashable | Lookup |
| --- | --- | --- |
| `list` | no | index O(1), value O(n) |
| `tuple` | if items are | index O(1) |
| `NamedTuple` | if fields are | by name or index |
| `dict` | no | key O(1) |
| `set` | no | `in` O(1) |
| `frozenset` | yes | `in` O(1) |
| `deque` | no | ends O(1), middle O(n) |
| `Counter` | no | key O(1) |
| `defaultdict` | no | key O(1) |
| `frozendict` | if values are | key O(1) |
| `array.array` | no | index O(1) |

| Container | Reach for it when |
| --- | --- |
| `list` | An ordered, growing sequence |
| `tuple` | A fixed record or a composite key |
| `NamedTuple` | A small immutable record with field names |
| `dict` | Mapping keys to values |
| `set` | Membership, deduplication, set algebra |
| `frozenset` | A set used as a key or set member |
| `deque` | Queues, sliding windows, last N items |
| `Counter` | Counting and tallies |
| `defaultdict` | Grouping, building nested data |
| `frozendict` | Constant lookup tables, mapping keys (3.15+) |
| `array.array` | Large homogeneous numbers, compact memory |

### Under the hood: shallow sizes of the same 1 000 ints

`sys.getsizeof` counts only the container itself (pointer arrays, hash tables), not
the `int` objects it refers to. The exception is `array.array`, which stores raw
8-byte machine integers instead of pointers. Hash-based containers cost about four
times as much as a list, because they keep empty slots and store a hash per entry:
that is the memory price of O(1) lookup. Sizes vary by version and platform.

```python
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
```

```text
list                 8,056 bytes
tuple                8,048 bytes
set                 32,984 bytes
frozenset           32,984 bytes
dict (value None)   36,952 bytes
deque                8,680 bytes
array('q')           8,080 bytes
```

### Key points

| Question | Answer |
| --- | --- |
| Need lookup by key? | `dict` (or `frozendict`) |
| Need fast membership? | `set` / `frozenset` |
| Need to use it as a key? | `tuple`, `frozenset`, `frozendict` |
| Need both ends fast? | `deque` |
| Millions of numbers? | `array.array` |

## 1.6.9 Method reference — `dict`

Costs are average-case. Every example starts from a fresh
`prices = {"dosa": 60, "idli": 40}`. Where an example changes `prices`, the Result
column shows the return value and, after a semicolon, what changed.

### Reading

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `d[key]` | read; `KeyError` if missing; O(1) | `prices["dosa"]` | `60` |
| `key in d` | membership on keys; O(1) | `"idli" in prices` | `True` |
| `len(d)` | number of keys; O(1) | `len(prices)` | `2` |
| `iter(d)` | iterate keys; O(n) | `list(iter(prices))` | `['dosa', 'idli']` |
| `get(key, default=None)` | read without raising; O(1) | `prices.get("vada", 0)` | `0` |
| `setdefault(key, default=None)` | read; insert default first if missing | `prices.setdefault("vada", 30)` | `30`; now stored |

### Inserting and removing

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `d[key] = value` | insert or replace; O(1) | `prices["dosa"] = 65` | `{'dosa': 65, 'idli': 40}` |
| `del d[key]` | delete; `KeyError` if missing | `del prices["idli"]` | `{'dosa': 60}` |
| `pop(key[, default])` | remove and return; O(1) | `prices.pop("idli")` | `40` |
| `popitem()` | remove last inserted pair; O(1) | `prices.popitem()` | `('idli', 40)` |
| `clear()` | remove everything; O(n) | `prices.clear()` | `None`; now `{}` |

### Merging

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `update(other=(), **kwargs)` | merge in place; O(k) | `prices.update(vada=30)` | `None`; `'vada': 30` added |
| `d1 \| d2` | new merged dict; right wins | `prices \| {"dosa": 50}` | `{'dosa': 50, 'idli': 40}` |
| `d1 \|= d2` | merge in place; O(m) | `prices \|= {"vada": 30}` | `'vada': 30` added |

### Views, copies and the rest

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `keys()`, `values()`, `items()` | live views; O(1) to create | `prices.keys() & {"dosa", "upma"}` | `{'dosa'}` |
| `copy()` | shallow copy; O(n) | `prices.copy() is prices` | `False` |
| `dict.fromkeys(iterable, value=None)` | every key → the same value | `dict.fromkeys(["dosa", "idli"], 0)` | `{'dosa': 0, 'idli': 0}` |
| `reversed(d)` | keys newest-first; O(n) | `list(reversed(prices))` | `['idli', 'dosa']` |
| `==` | same pairs; order ignored | `prices == {"idli": 40, "dosa": 60}` | `True` |

### The trickier methods in full

**`setdefault(key, default=None)`** returns the existing value untouched, and
inserts `None` when you leave out the default.

```python
price_list = {"dosa": 60}
print(
    f"{price_list.setdefault('dosa', 99)=}, "
    f"{price_list.setdefault('vada', 30)=}"
)
print(f"{price_list.setdefault('upma')=}, {price_list=}")
```

```text
price_list.setdefault('dosa', 99)=60, price_list.setdefault('vada', 30)=30
price_list.setdefault('upma')=None,
  price_list={'dosa': 60, 'vada': 30, 'upma': None}
```

**`pop(key[, default])`** raises only when there is no default.

```python
price_list = {"dosa": 60, "idli": 40}
print(
    f"{price_list.pop('idli')=}, {price_list.pop('idli', None)=}, "
    f"{price_list=}"
)
print(
    "pop missing, no default: "
    f"{raised_error_name(lambda: price_list.pop('idli'))}"
)
```

```text
price_list.pop('idli')=40, price_list.pop('idli', None)=None,
  price_list={'dosa': 60}
pop missing, no default: KeyError
```

**`popitem()`** is LIFO: the most recently inserted pair comes out first, and an
empty dict raises `KeyError`.

```python
price_list = {"dosa": 60, "idli": 40, "vada": 30}
print(
    f"{price_list.popitem()=}, {price_list.popitem()=}, {price_list=}"
)
print(f"popitem on empty: {raised_error_name({}.popitem)}")
```

```text
price_list.popitem()=('vada', 30), price_list.popitem()=('idli', 40),
  price_list={'dosa': 60}
popitem on empty: KeyError
```

**`update(other=(), **kwargs)`** returns `None`, like every in-place mutator in
Python. Writing `prices = prices.update(...)` is a classic bug: it sets `prices` to
`None`.

```python
price_list = {"dosa": 60}
update_result = price_list.update({"idli": 40}, vada=30)
price_list.update([("upma", 45)])
print(f"{price_list=}, {update_result=}")
```

```text
price_list={'dosa': 60, 'idli': 40, 'vada': 30, 'upma': 45},
  update_result=None
```

**`d1 | d2` and `d1 |= d2`**: `|` builds a new dict; `|=` changes the existing one,
so an alias sees the change.

```python
base_prices = {"dosa": 60, "idli": 40}
festival_prices = {"dosa": 50}
merged_prices = base_prices | festival_prices
print(f"{merged_prices=}, {base_prices=}")
prices_alias = base_prices
base_prices |= festival_prices
print(f"{base_prices=}, {base_prices is prices_alias=}")
```

```text
merged_prices={'dosa': 50, 'idli': 40}, base_prices={'dosa': 60, 'idli': 40}
base_prices={'dosa': 50, 'idli': 40}, base_prices is prices_alias=True
```

**`keys()`, `values()`, `items()`**: the views are live, and key and item views
support set operators.

```python
price_list = {"dosa": 60, "idli": 40}
price_items = price_list.items()
price_list["vada"] = 30
print(f"{price_items=}  (includes vada: the view is live)")
print(f"{list(price_list.values())=}")
print(
    f"{sorted(price_list.keys() - {'idli'})=}, "
    f"{price_items & {('vada', 30)}=}"
)
```

```text
price_items=dict_items([('dosa', 60), ('idli', 40), ('vada', 30)])
  (includes vada: the view is live)
list(price_list.values())=[60, 40, 30]
sorted(price_list.keys() - {'idli'})=['dosa', 'vada'],
  price_items & {('vada', 30)}={('vada', 30)}
```

**`copy()`** is shallow: rebinding a key in the copy is independent, but a nested
list is shared.

```python
price_list = {"dosa": 60, "combo": ["dosa", "chai"]}
price_copy = price_list.copy()
price_copy["dosa"] = 70
print(f"{price_list['dosa']=}, {price_copy['dosa']=}")
print(f"{price_copy['combo'] is price_list['combo']=}  (shallow)")
```

```text
price_list['dosa']=60, price_copy['dosa']=70
price_copy['combo'] is price_list['combo']=True  (shallow)
```

**`clear()`** empties the dict in place, so aliases see the empty dict. Rebinding
with `price_list = {}` would leave the alias holding the old data.

```python
price_list = {"dosa": 60, "idli": 40}
price_alias = price_list
print(f"{price_list.clear()=}, {price_alias=}")
```

```text
price_list.clear()=None, price_alias={}
```

**`dict.fromkeys(iterable, value=None)`** shares one value object across all keys,
which is safe for immutable values only.

```python
stock_flags = dict.fromkeys(["dosa", "idli", "vada"], False)
shared_lists = dict.fromkeys(["T1", "T2"], [])
print(f"{stock_flags=}")
print(f"{shared_lists['T1'] is shared_lists['T2']=}  (one list, see 1.6.3)")
```

```text
stock_flags={'dosa': False, 'idli': False, 'vada': False}
shared_lists['T1'] is shared_lists['T2']=True  (one list, see 1.6.3)
```

**`reversed(d)`** (3.8+) iterates keys newest-first, and also works on the views.

```python
price_list = {"dosa": 60, "idli": 40, "vada": 30}
print(f"{list(reversed(price_list))=}")
print(f"{list(reversed(price_list.items()))=}")
```

```text
list(reversed(price_list))=['vada', 'idli', 'dosa']
list(reversed(price_list.items()))=[('vada', 30), ('idli', 40), ('dosa', 60)]
```

**`==`** ignores order and compares values with `==`, so `60` equals `60.0`.

```python
print(f"{ {'dosa': 60, 'idli': 40} == {'idli': 40, 'dosa': 60}=}")
print(f"{ {'dosa': 60} == {'dosa': 60.0}=}  (60 == 60.0)")
print(f"{ {'dosa': 60} == {'dosa': 65}=}")
```

```text
 {'dosa': 60, 'idli': 40} == {'idli': 40, 'dosa': 60}=True
 {'dosa': 60} == {'dosa': 60.0}=True  (60 == 60.0)
 {'dosa': 60} == {'dosa': 65}=False
```

### Key points

| Remember | Why |
| --- | --- |
| Mutators return `None` | `update`, `clear` change in place |
| `popitem` is LIFO | Newest pair comes out first |
| Views are live | Snapshot with `list(...)` |
| `fromkeys` shares the value | Use a comprehension for lists |

## 1.6.10 Method reference — `set` and `frozenset`

Every example starts from fresh sets `tickets = {101, 102, 103}` and
`others = {103, 104}`. Small integers hash to themselves, so these sets print in the
same order on every run (which is why `{104, 101, 102}` can appear: the order comes
from the hash table slots, not from sorting).

### Adding and removing (mutate)

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `add(x)` | add one element | `tickets.add(104)` | `{104, 101, 102, 103}` |
| `remove(x)` | delete; `KeyError` if absent | `tickets.remove(999)` | `KeyError` |
| `discard(x)` | delete; silent if absent | `tickets.discard(999)` | `None`; unchanged |
| `pop()` | remove an arbitrary element | `tickets.pop()` | `101` (do not rely on it) |
| `clear()` | empty in place | `tickets.clear()` | `set()` |
| `copy()` | shallow copy (no mutation) | `tickets.copy()` | `{101, 102, 103}` |

### Set algebra (new set)

| Method / operator | What it does | Example | Result |
| --- | --- | --- | --- |
| `union(*others)` / `a \| b` | in either | `tickets \| others` | `{101, 102, 103, 104}` |
| `intersection(*others)` / `a & b` | in both | `tickets & others` | `{103}` |
| `difference(*others)` / `a - b` | only in `a` | `tickets - others` | `{101, 102}` |
| `symmetric_difference(other)` / `a ^ b` | in exactly one | `tickets ^ others` | `{104, 101, 102}` |

### In-place algebra (mutate)

| Method / operator | What it does | Example | Result |
| --- | --- | --- | --- |
| `update` / `\|=` | add all of other | `tickets \|= others` | `{101, 102, 103, 104}` |
| `intersection_update` / `&=` | keep common only | `tickets &= others` | `{103}` |
| `difference_update` / `-=` | remove other's | `tickets -= others` | `{101, 102}` |
| `symmetric_difference_update` / `^=` | keep in exactly one | `tickets ^= others` | `{104, 101, 102}` |

### Relations (no mutation)

| Method / operator | What it does | Example | Result |
| --- | --- | --- | --- |
| `issubset(other)` / `<=` | every element in other | `{101} <= tickets` | `True` |
| `issuperset(other)` / `>=` | contains every element | `tickets.issuperset([101])` | `True` |
| `<` / `>` | proper subset / superset | `tickets < tickets` | `False` |
| `isdisjoint(other)` | no common element | `tickets.isdisjoint(others)` | `False` |
| `x in s` | membership; O(1) average | `103 in tickets` | `True` |

Methods accept any iterable; operators require sets (or frozensets) on both sides.
`frozenset` has only the non-mutating methods and is hashable.

### The trickier methods in full

**`remove(x)` vs `discard(x)`**:

```python
open_tickets = {101, 102, 103}
open_tickets.remove(101)
open_tickets.discard(999)
print(f"{open_tickets=}")
print(f"remove missing: {raised_error_name(lambda: open_tickets.remove(999))}")
```

```text
open_tickets={102, 103}
remove missing: KeyError
```

**`pop()`** takes an arbitrary element and raises `KeyError` on an empty set.

```python
open_tickets = {101, 102, 103}
closed_ticket = open_tickets.pop()
print(f"{closed_ticket in {101, 102, 103}=}, {len(open_tickets)=}")
print(f"pop on empty: {raised_error_name(set().pop)}")
```

```text
closed_ticket in {101, 102, 103}=True, len(open_tickets)=2
pop on empty: KeyError
```

**`clear()` and `copy()`**: the copy is independent of the original.

```python
open_tickets = {101, 102}
ticket_snapshot = open_tickets.copy()
open_tickets.clear()
print(f"{open_tickets=}, {ticket_snapshot=}")
```

```text
open_tickets=set(), ticket_snapshot={101, 102}
```

**The algebra methods take several iterables at once**, which the operators cannot.

```python
team_a_tickets = {101, 102, 103}
team_b_tickets = {103, 104}
print(f"{team_a_tickets | team_b_tickets=}")
print(f"{team_a_tickets.union(team_b_tickets, [105])=}")
print(f"{team_a_tickets - team_b_tickets=}")
print(f"{team_a_tickets.difference(team_b_tickets, [102])=}")
print(f"{team_a_tickets ^ team_b_tickets=}")
print(f"{team_a_tickets.symmetric_difference([103, 104])=}")
team_b_tickets = {103, 104, 101}
print(f"{team_a_tickets & team_b_tickets=}")
print(f"{team_a_tickets.intersection(team_b_tickets, [101, 999])=}")
```

```text
team_a_tickets | team_b_tickets={101, 102, 103, 104}
team_a_tickets.union(team_b_tickets, [105])={101, 102, 103, 104, 105}
team_a_tickets - team_b_tickets={101, 102}
team_a_tickets.difference(team_b_tickets, [102])={101}
team_a_tickets ^ team_b_tickets={104, 101, 102}
team_a_tickets.symmetric_difference([103, 104])={104, 101, 102}
team_a_tickets & team_b_tickets={101, 103}
team_a_tickets.intersection(team_b_tickets, [101, 999])={101}
```

**In-place updates** return `None` and change the set itself.

```python
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
```

```text
after update:                      {104, 101, 102, 103}
after intersection_update:         {104, 102, 103}
after difference_update:           {102, 103}
after symmetric_difference_update: {106, 102}
after |= &= -= ^=:                 {102, 110, 111}
```

**Subset tests**: `<` and `>` require the sets to differ.

```python
urgent_tickets = {101, 103}
open_tickets = {101, 102, 103}
print(
    f"{urgent_tickets.issubset(open_tickets)=}, "
    f"{urgent_tickets <= open_tickets=}"
)
print(
    f"{open_tickets.issuperset([101])=}, "
    f"{open_tickets >= urgent_tickets=}"
)
print(f"{urgent_tickets < open_tickets=}, {open_tickets < open_tickets=}")
print(f"{open_tickets > urgent_tickets=}")
```

```text
urgent_tickets.issubset(open_tickets)=True, urgent_tickets <= open_tickets=True
open_tickets.issuperset([101])=True, open_tickets >= urgent_tickets=True
urgent_tickets < open_tickets=True, open_tickets < open_tickets=False
open_tickets > urgent_tickets=True
```

**`isdisjoint(other)`** accepts any iterable.

```python
open_tickets = {101, 102}
print(
    f"{open_tickets.isdisjoint({201, 202})=}, "
    f"{open_tickets.isdisjoint([102, 300])=}"
)
```

```text
open_tickets.isdisjoint({201, 202})=True,
  open_tickets.isdisjoint([102, 300])=False
```

### `frozenset` specifics

**Methods accept any iterable; operators require sets on both sides.** A `set` and a
`frozenset` mix freely, and the result takes the type of the **left** operand.

```python
open_tickets = {101, 102}
print(f"{open_tickets.union(range(103, 105))=}")
print(
    "set | range: "
    f"{raised_error_name(lambda: open_tickets | range(103, 105))}"
)
print(
    f"{type(frozenset({1}) | {2}).__name__=}, "
    f"{type({2} | frozenset({1})).__name__=}"
)
```

```text
open_tickets.union(range(103, 105))={104, 101, 102, 103}
set | range: TypeError
type(frozenset({1}) | {2}).__name__='frozenset',
  type({2} | frozenset({1})).__name__='set'
```

**`frozenset` has only the non-mutating methods and is hashable.** Mutators such as
`add` do not exist on it at all (so the error is `AttributeError`), and it can be a
dict key or an element of another set.

```python
weekend_days = frozenset({"sat", "sun"})
print(f"{hasattr(weekend_days, 'add')=}, {hasattr(weekend_days, 'union')=}")
print(f"add: {raised_error_name(lambda: weekend_days.add('fri'))}")
print(f"{sorted(weekend_days | {'fri'})=}  (returns a new frozenset)")
schedules = {weekend_days: "relaxed", frozenset({"mon"}): "busy"}
print(f"{schedules[frozenset({'sun', 'sat'})]=}")
set_of_sets = {frozenset({1, 2}), frozenset({2, 1}), frozenset({3})}
print(f"{len(set_of_sets)=}")
```

```text
hasattr(weekend_days, 'add')=False, hasattr(weekend_days, 'union')=True
add: AttributeError
sorted(weekend_days | {'fri'})=['fri', 'sat', 'sun']  (returns a new frozenset)
schedules[frozenset({'sun', 'sat'})]='relaxed'
len(set_of_sets)=2
```

**`x in s` is O(1) on average**: one hash and a probe, independent of the set size.
A list has to scan every element. Timings vary by machine.

```python
ticket_numbers = list(range(100_000))
ticket_set = frozenset(ticket_numbers)
list_seconds = timeit.timeit(lambda: -1 in ticket_numbers, number=50)
set_seconds = timeit.timeit(lambda: -1 in ticket_set, number=50)
print(f"list: {list_seconds / 50 * 1e6:9.2f} µs per lookup")
print(f"set:  {set_seconds / 50 * 1e6:9.3f} µs per lookup")
```

```text
list:    548.96 µs per lookup
set:      0.043 µs per lookup
```

### Key points

| Remember | Why |
| --- | --- |
| `pop()` is arbitrary | Sets have no order |
| Operators need sets | Methods take any iterable |
| Mixed types | Result follows the left operand |
| `frozenset` | No mutators; hashable |

## 1.6.11 Method reference — `collections`

The `collections` types are summarised below, one table per type. Mutating examples
show the container **after** the call. `namedtuple` was covered in 1.5.10 and gets a
single reminder row.

### `deque`

Every example starts from `calls = deque(["asha", "ravi"])`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `append(x)` | add on the right; O(1) | `calls.append("meena")` | `deque(['asha', 'ravi', 'meena'])` |
| `appendleft(x)` | add on the left; O(1) | `calls.appendleft("vip")` | `deque(['vip', 'asha', 'ravi'])` |
| `pop()` | remove right; `IndexError` if empty | `calls.pop()` | `'ravi'` |
| `popleft()` | remove left; O(1) | `calls.popleft()` | `'asha'` |
| `extend(iterable)` | append each item | `calls.extend(["x", "y"])` | `deque(['asha', 'ravi', 'x', 'y'])` |
| `extendleft(iterable)` | appendleft each (reverses) | `calls.extendleft(["x", "y"])` | `deque(['y', 'x', 'asha', 'ravi'])` |
| `rotate(n)` | rotate `n` steps right | `calls.rotate(1)` | `deque(['ravi', 'asha'])` |
| `insert(i, x)` | insert before `i`; O(n) | `calls.insert(1, "zoe")` | `deque(['asha', 'zoe', 'ravi'])` |
| `remove(x)` | delete first match | `calls.remove("asha")` | `deque(['ravi'])` |
| `count(x)` | count matches | `calls.count("asha")` | `1` |
| `index(x)` | position of first match | `calls.index("ravi")` | `1` |
| `reverse()` | reverse in place | `calls.reverse()` | `deque(['ravi', 'asha'])` |
| `clear()` | remove every item | `calls.clear()` | `deque([])` |
| `copy()` | shallow copy | `calls.copy()` | `deque(['asha', 'ravi'])` |
| `maxlen` | bound, or `None` | `deque([1, 2, 3], maxlen=2)` | `deque([2, 3], maxlen=2)` |

### `Counter`

Every example starts from `views = Counter(["/home", "/cart", "/home"])`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `most_common(n)` | top `n` pairs | `views.most_common(1)` | `[('/home', 2)]` |
| `elements()` | repeat each by count | `list(views.elements())` | `['/home', '/home', '/cart']` |
| `update(x)` | add counts | `views.update(["/home"])` | `Counter({'/home': 3, '/cart': 1})` |
| `subtract(x)` | subtract; keeps ≤ 0 | `views.subtract({"/cart": 2})` | `Counter({'/home': 2, '/cart': -1})` |
| `total()` | sum of counts (3.10+) | `views.total()` | `3` |
| `+` | add counts | `views + Counter({"/pay": 1})` | `Counter({'/home': 2, '/cart': 1, '/pay': 1})` |
| `-` | subtract; drop ≤ 0 | `views - Counter({"/home": 5})` | `Counter({'/cart': 1})` |
| `&` | minimum per item | `views & Counter({"/home": 1})` | `Counter({'/home': 1})` |
| `\|` | maximum per item | `views \| Counter({"/cart": 4})` | `Counter({'/cart': 4, '/home': 2})` |
| missing key | counts as 0; not inserted | `views["/pay"]` | `0` |

### `defaultdict`, `OrderedDict` and `namedtuple`

The examples use `groups = defaultdict(list)` and
`tabs = OrderedDict(mail=1, docs=2)`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `default_factory` | factory for misses | `groups.default_factory` | `<class 'list'>` |
| `__missing__(key)` | create, store, return | `groups.__missing__("b")` | `[]`; now stored |
| dict methods | `get`, `in` skip the factory | `groups.get("a")` | `None` |
| `move_to_end(key, last=True)` | move to end or front | `tabs.move_to_end("mail")` | order `['docs', 'mail']` |
| `popitem(last=True)` | newest, or oldest | `tabs.popitem(last=False)` | `('mail', 1)` |
| `==` | order-sensitive | `tabs == OrderedDict(docs=2, mail=1)` | `False` |
| `namedtuple` | see 1.5.10 | `Point(1, 2)._replace(y=5)` | `Point(x=1, y=5)` |

### `ChainMap`

The examples use `user = {"theme": "dark"}`,
`base = {"theme": "light", "size": 14}` and `settings = ChainMap(user, base)`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `maps` | the list of mappings | `settings.maps[0]` | `{'theme': 'dark'}` |
| lookup | first mapping wins | `settings["size"]` | `14` |
| `new_child(m=None)` | add a layer in front | `settings.new_child({"size": 18})["size"]` | `18` |
| `parents` | all but the first | `settings.parents["theme"]` | `'light'` |
| writes | go to `maps[0]` only | `settings["size"] = 16` | `user` gains `'size': 16` |

### `deque` methods in full

**`pop()` and `popleft()`** raise `IndexError` (not `KeyError`) on an empty deque,
like a list.

```python
call_queue = deque(["caller-1", "caller-2"])
print(f"{call_queue.pop()=}, {call_queue=}")
print(f"pop on empty: {raised_error_name(deque().pop)}")
call_queue = deque(["caller-1", "caller-2"])
print(f"{call_queue.popleft()=}, {call_queue=}")
print(f"popleft on empty: {raised_error_name(deque().popleft)}")
```

```text
call_queue.pop()='caller-2', call_queue=deque(['caller-1'])
pop on empty: IndexError
call_queue.popleft()='caller-1', call_queue=deque(['caller-2'])
popleft on empty: IndexError
```

**`extend` vs `extendleft`**: `extendleft` adds each item to the front in turn, so
passing the items in reverse order gives the natural order.

```python
call_queue = deque(["caller-1"])
call_queue.extend(["caller-2", "caller-3"])
print(f"{call_queue=}")
call_queue = deque(["caller-3"])
call_queue.extendleft(["caller-2", "caller-1"])
print(f"{call_queue=}")
```

```text
call_queue=deque(['caller-1', 'caller-2', 'caller-3'])
call_queue=deque(['caller-1', 'caller-2', 'caller-3'])
```

**`rotate(n)`**: positive steps go right, negative steps undo them.

```python
shift_rota = deque(["asha", "ravi", "meena", "john"])
shift_rota.rotate(1)
print(f"{shift_rota=}")
shift_rota.rotate(-1)
print(f"{shift_rota=}")
```

```text
shift_rota=deque(['john', 'asha', 'ravi', 'meena'])
shift_rota=deque(['asha', 'ravi', 'meena', 'john'])
```

**`insert(i, x)`** is O(n) towards the middle, and raises `IndexError` on a full
bounded deque (it cannot decide which end to drop).

```python
call_queue = deque(["caller-1", "caller-3"])
call_queue.insert(1, "caller-2")
print(f"{call_queue=}")
bounded_queue = deque([1, 2], maxlen=2)
print(
    "insert into full deque: "
    f"{raised_error_name(lambda: bounded_queue.insert(0, 0))}"
)
```

```text
call_queue=deque(['caller-1', 'caller-2', 'caller-3'])
insert into full deque: IndexError
```

**`remove`, `count` and `index`** search by value, and raise `ValueError` when the
value is absent.

```python
call_queue = deque(["caller-1", "spam", "caller-2", "spam"])
call_queue.remove("spam")
print(f"{call_queue=}")
print(
    "remove missing: "
    f"{raised_error_name(lambda: call_queue.remove('nobody'))}"
)
call_queue = deque(["asha", "ravi", "asha"])
print(f"{call_queue.count('asha')=}, {call_queue.count('zoe')=}")
print(f"{call_queue.index('asha')=}, {call_queue.index('asha', 1)=}")
print(f"index missing: {raised_error_name(lambda: call_queue.index('zoe'))}")
```

```text
call_queue=deque(['caller-1', 'caller-2', 'spam'])
remove missing: ValueError
call_queue.count('asha')=2, call_queue.count('zoe')=0
call_queue.index('asha')=0, call_queue.index('asha', 1)=2
index missing: ValueError
```

**`reverse()` and `clear()`** work in place and return `None`.

```python
call_queue = deque([1, 2, 3])
print(f"{call_queue.reverse()=}, {call_queue=}")
call_queue.clear()
print(f"{call_queue=}, {len(call_queue)=}")
```

```text
call_queue.reverse()=None, call_queue=deque([3, 2, 1])
call_queue=deque([]), len(call_queue)=0
```

**`copy()` keeps `maxlen`, and `maxlen` drops from the opposite end.** Appending on
the left of a full deque drops an item from the right.

```python
recent_calls = deque(["asha", "ravi"], maxlen=3)
calls_copy = recent_calls.copy()
calls_copy.append("meena")
print(f"{recent_calls=}")
print(f"{calls_copy=}")
recent_calls = deque(maxlen=2)
recent_calls.extend(["asha", "ravi", "meena"])
recent_calls.appendleft("john")  # drops from the right
print(f"{recent_calls=}, {recent_calls.maxlen=}, {deque().maxlen=}")
```

```text
recent_calls=deque(['asha', 'ravi'], maxlen=3)
calls_copy=deque(['asha', 'ravi', 'meena'], maxlen=3)
recent_calls=deque(['john', 'ravi'], maxlen=2), recent_calls.maxlen=2,
  deque().maxlen=None
```

> **Note:** in the notebook the two `copy()` results are printed on one line; here
> they are printed with two `print` calls so they fit the screen. The values are the
> same.

### `Counter` methods in full

**`most_common(n)`**: no argument returns every pair, largest first.

```python
page_views = Counter(["/home", "/cart", "/home", "/pay", "/cart", "/home"])
print(f"{page_views.most_common(2)=}")
print(f"{page_views.most_common()=}")
```

```text
page_views.most_common(2)=[('/home', 3), ('/cart', 2)]
page_views.most_common()=[('/home', 3), ('/cart', 2), ('/pay', 1)]
```

**`elements()`** skips items whose count is zero or negative.

```python
ingredient_counts = Counter(egg=2, flour=1, salt=0)
print(f"{list(ingredient_counts.elements())=}")
```

```text
list(ingredient_counts.elements())=['egg', 'egg', 'flour']
```

**`update` adds and `subtract` subtracts**, from either an iterable or a mapping.

```python
page_views = Counter({"/home": 3})
page_views.update(["/home", "/cart"])
page_views.update({"/cart": 5})
print(f"{page_views=}")
warehouse_stock = Counter(soap=5, tea=2)
warehouse_stock.subtract({"tea": 3, "soap": 1})
print(f"{warehouse_stock=}")
```

```text
page_views=Counter({'/cart': 6, '/home': 4})
warehouse_stock=Counter({'soap': 4, 'tea': -1})
```

**`total()`** is shorthand for `sum(counter.values())`.

```python
page_views = Counter({"/home": 3, "/cart": 2})
print(f"{page_views.total()=}, {sum(page_views.values())=}")
```

```text
page_views.total()=5, sum(page_views.values())=5
```

**`+ - & |`**, plus unary `+`, which drops non-positive counts.

```python
shop_a = Counter(soap=3, tea=1)
shop_b = Counter(soap=1, tea=4, rice=2)
print(f"{shop_a + shop_b=}")
print(f"{shop_a - shop_b=}")
print(f"{shop_a & shop_b=}, {shop_a | shop_b=}")
print(f"{+Counter(soap=2, tea=-1, rice=0)=}")
```

```text
shop_a + shop_b=Counter({'tea': 5, 'soap': 4, 'rice': 2})
shop_a - shop_b=Counter({'soap': 2})
shop_a & shop_b=Counter({'soap': 1, 'tea': 1}),
  shop_a | shop_b=Counter({'tea': 4, 'soap': 3, 'rice': 2})
+Counter(soap=2, tea=-1, rice=0)=Counter({'soap': 2})
```

**Missing keys count as 0.** Reading one returns `0` and does **not** insert it,
unlike `defaultdict(int)`; `+= 1` then inserts it as usual.

```python
page_views = Counter({"/home": 3})
print(f"{page_views['/missing']=}, {'/missing' in page_views=}")
page_views["/new"] += 1
print(f"{page_views=}")
```

```text
page_views['/missing']=0, '/missing' in page_views=False
page_views=Counter({'/home': 3, '/new': 1})
```

### `defaultdict` methods in full

**`default_factory`** can be changed later; setting it to `None` turns the
defaultdict back into plain-dict behaviour.

```python
tickets_by_agent = defaultdict(set)
tickets_by_agent["asha"].add(101)
print(f"{tickets_by_agent.default_factory=}, {dict(tickets_by_agent)=}")
tickets_by_agent.default_factory = None
print(
    "missing key, factory None: "
    f"{raised_error_name(lambda: tickets_by_agent['ravi'])}"
)
```

```text
tickets_by_agent.default_factory=<class 'set'>,
  dict(tickets_by_agent)={'asha': {101}}
missing key, factory None: KeyError
```

**`__missing__`** is what `d[key]` calls on a miss: it runs the factory, stores the
value and returns it.

```python
page_counts = defaultdict(int)
print(f"{page_counts.__missing__('/home')=}, {dict(page_counts)=}")
page_counts["/cart"] += 1  # __getitem__ miss → __missing__ → 0, then += 1
print(f"{dict(page_counts)=}")
```

```text
page_counts.__missing__('/home')=0, dict(page_counts)={'/home': 0}
dict(page_counts)={'/home': 0, '/cart': 1}
```

**All `dict` methods** work, because it *is* a dict subclass. `get`, `in` and
`setdefault` do not call the factory.

```python
page_counts = defaultdict(int, {"/home": 3})
print(f"{isinstance(page_counts, dict)=}")
print(f"{page_counts.get('/cart')=}, {'/cart' in page_counts=}  (no insert)")
page_counts.update({"/pay": 1})
print(f"{sorted(page_counts.items())=}, {page_counts.pop('/pay')=}")
```

```text
isinstance(page_counts, dict)=True
page_counts.get('/cart')=None, '/cart' in page_counts=False  (no insert)
sorted(page_counts.items())=[('/home', 3), ('/pay', 1)],
  page_counts.pop('/pay')=1
```

### `OrderedDict` methods in full

**`move_to_end(key, last=True)`** raises `KeyError` for a missing key.

```python
browser_tabs = OrderedDict.fromkeys(["mail", "docs", "news"])
browser_tabs.move_to_end("mail")
print(f"{list(browser_tabs)=}")
browser_tabs.move_to_end("news", last=False)
print(f"{list(browser_tabs)=}")
print(
    "missing key: "
    f"{raised_error_name(lambda: browser_tabs.move_to_end('chat'))}"
)
```

```text
list(browser_tabs)=['docs', 'news', 'mail']
list(browser_tabs)=['news', 'docs', 'mail']
missing key: KeyError
```

**`popitem(last=True)`** removes the newest pair, or the oldest with `last=False`.

```python
browser_tabs = OrderedDict(mail=1, docs=2, news=3)
print(
    f"{browser_tabs.popitem()=}, "
    f"{browser_tabs.popitem(last=False)=}, {browser_tabs=}"
)
```

```text
browser_tabs.popitem()=('news', 3),
  browser_tabs.popitem(last=False)=('mail', 1),
  browser_tabs=OrderedDict({'docs': 2})
```

**Order-sensitive `==`** applies only between two `OrderedDict`s.

```python
first_order = OrderedDict(mail=1, docs=2)
second_order = OrderedDict(docs=2, mail=1)
print(f"{first_order == second_order=}, {first_order == dict(second_order)=}")
```

```text
first_order == second_order=False, first_order == dict(second_order)=True
```

### `ChainMap` methods in full

**`maps`** is an ordinary, editable list of the underlying mappings, searched front
to back.

```python
built_in_defaults = {"theme": "light", "font_size": 14}
user_overrides = {"theme": "dark"}
layered_settings = ChainMap(user_overrides, built_in_defaults)
print(f"{layered_settings.maps=}")
print(f"{layered_settings['theme']=}, {layered_settings['font_size']=}")
```

```text
layered_settings.maps=[{'theme': 'dark'}, {'theme': 'light', 'font_size': 14}]
layered_settings['theme']='dark', layered_settings['font_size']=14
```

**`new_child(m=None)`** returns a new ChainMap with an extra mapping in front and
leaves the original alone: handy for nested scopes.

```python
built_in_defaults = {"theme": "light", "font_size": 14}
layered_settings = ChainMap(built_in_defaults)
session_settings = layered_settings.new_child({"font_size": 18})
print(
    f"{session_settings['font_size']=}, "
    f"{layered_settings['font_size']=}"
)
print(f"{len(session_settings.maps)=}")
```

```text
session_settings['font_size']=18, layered_settings['font_size']=14
len(session_settings.maps)=2
```

**`parents`** is a ChainMap of every mapping except the first. This is exactly how
Python's own name lookup works (local, enclosing, global), which Unit 1.10 covers.

```python
scope_chain = ChainMap({"x": "local"}, {"x": "enclosing"}, {"x": "global"})
print(f"{scope_chain['x']=}, {scope_chain.parents['x']=}")
print(f"{scope_chain.parents.parents['x']=}")
```

```text
scope_chain['x']='local', scope_chain.parents['x']='enclosing'
scope_chain.parents.parents['x']='global'
```

**Writes go to the first mapping.** Assignment, `del` and `pop` touch only
`maps[0]`; deleting a key that exists only in a later mapping raises `KeyError`.

```python
built_in_defaults = {"theme": "light"}
user_overrides: dict[str, str] = {}
layered_settings = ChainMap(user_overrides, built_in_defaults)
layered_settings["theme"] = "dark"
print(f"{user_overrides=}, {built_in_defaults=}")
del layered_settings["theme"]
print(f"{layered_settings['theme']=}  (the default shows through again)")
print(
    "del a key only in a later map: "
    f"{raised_error_name(lambda: layered_settings.pop('theme'))}"
)
```

```text
user_overrides={'theme': 'dark'}, built_in_defaults={'theme': 'light'}
layered_settings['theme']='light'  (the default shows through again)
del a key only in a later map: KeyError
```

### `namedtuple` reminder

Covered in 1.5.6 and 1.5.10 (`_fields`, `_make`, `_asdict`, `_replace`, defaults).

```python
Coordinates = namedtuple("Coordinates", ["latitude", "longitude"])
office_location = Coordinates(18.52, 73.86)
print(f"{Coordinates._fields=}")
print(f"{office_location._replace(longitude=73.9)=}")
```

```text
Coordinates._fields=('latitude', 'longitude')
office_location._replace(longitude=73.9)=
  Coordinates(latitude=18.52, longitude=73.9)
```

> **Note:** the notebook prints these two values on one line; they are split into two
> `print` calls here to fit the screen.

### Key points

| Type | Gotcha |
| --- | --- |
| `deque` | Empty pops raise `IndexError` |
| `Counter` | `subtract` keeps negatives; `-` drops them |
| `defaultdict` | Only `d[key]` runs the factory |
| `OrderedDict` | `==` is order-sensitive only vs another OD |
| `ChainMap` | Writes and deletes hit `maps[0]` only |

## 1.6.12 Common dictionary patterns

These are the dictionary idioms you will write every week. The first two reuse the
`LogEntry` record from 1.5.6 (defined in this unit's setup), which the Phase 1
project builds on.

### Counting

The manual `get(key, 0) + 1` loop and `Counter` give the same counts. `Counter` is
shorter, says what it means, and also gives you `most_common`. Because `Counter` is a
dict subclass, the two results even compare equal.

```python
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
    level_counts_manual[log_entry.level] = (
        level_counts_manual.get(log_entry.level, 0) + 1
    )
level_counts = Counter(log_entry.level for log_entry in access_log)
print(f"{level_counts_manual=}")
print(
    f"{level_counts.most_common(1)=}, "
    f"{level_counts_manual == level_counts=}"
)
```

```text
level_counts_manual={'INFO': 3, 'ERROR': 2, 'WARNING': 1}
level_counts.most_common(1)=[('INFO', 3)],
  level_counts_manual == level_counts=True
```

### Grouping

`defaultdict(list)` and `setdefault(key, []).append(...)` both collect items per key.
Convert a defaultdict to a plain `dict` before returning it, so that later reads of
missing keys raise instead of silently inserting.

```python
messages_by_level: defaultdict[str, list[str]] = defaultdict(list)
for log_entry in access_log:
    messages_by_level[log_entry.level].append(log_entry.message)
status_codes_by_level: dict[str, list[int]] = {}
for log_entry in access_log:
    status_codes_by_level.setdefault(log_entry.level, []).append(
        log_entry.status_code
    )
print(f"{dict(messages_by_level)=}")
print(f"{status_codes_by_level=}")
```

```text
dict(messages_by_level)={'INFO': ['GET /home', 'GET /cart', 'GET /pay'],
  'ERROR': ['db timeout', 'gateway timeout'], 'WARNING': ['slow query']}
status_codes_by_level={'INFO': [200, 200, 200], 'ERROR': [500, 504],
  'WARNING': [200]}
```

### Indexing records by ID

One comprehension turns a list of rows into an O(1) lookup table, the Python version
of `Object.fromEntries(rows.map(r => [r.id, r]))`. If two rows share an ID, the last
one silently wins, so compare the lengths when duplicates would be a bug.

```python
customer_rows = [
    {"id": 7, "name": "Asha", "city": "Pune"},
    {"id": 3, "name": "Ravi", "city": "Goa"},
    {"id": 9, "name": "Meena", "city": "Pune"},
]
customers_by_id = {row["id"]: row for row in customer_rows}
print(f"{customers_by_id[3]['name']=}, {sorted(customers_by_id)=}")
print(f"{len(customers_by_id) == len(customer_rows)=}  (no duplicate IDs)")
```

```text
customers_by_id[3]['name']='Ravi', sorted(customers_by_id)=[3, 7, 9]
len(customers_by_id) == len(customer_rows)=True  (no duplicate IDs)
```

### Inverting a mapping

Swapping keys and values works when the values are unique and hashable. With
duplicate values, the naive inverse loses entries; group instead.

```python
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
```

```text
country_codes['Nepal']='NP'
naive_inverse={'Pune': 'meena', 'Goa': 'ravi'}  (asha was overwritten)
dict(people_by_city)={'Pune': ['asha', 'meena'], 'Goa': ['ravi']}
```

### Sorting by value

Sort `items()` with a key function on the value, then rebuild a dict, which keeps the
sorted order. `max(d, key=d.__getitem__)` (or `key=d.get`) finds the key with the
largest value.

```python
dish_ratings = {"dosa": 4.7, "idli": 4.2, "vada": 4.5}
ratings_high_to_low = dict(
    sorted(dish_ratings.items(), key=lambda pair: pair[1], reverse=True)
)
print(f"{ratings_high_to_low=}")
print(f"{max(dish_ratings, key=dish_ratings.__getitem__)=}")
print(f"{sorted(dish_ratings, key=dish_ratings.__getitem__)=}")
```

```text
ratings_high_to_low={'dosa': 4.7, 'vada': 4.5, 'idli': 4.2}
max(dish_ratings, key=dish_ratings.__getitem__)='dosa'
sorted(dish_ratings, key=dish_ratings.__getitem__)=['idli', 'vada', 'dosa']
```

### Safe nested access

Python has no optional chaining (`config?.db?.port`). The usual substitute is
`config.get("db", {}).get("port")`, which avoids `KeyError` at each level. It fails
when a key *exists* with the value `None`, because the default is used only for
missing keys; `(config.get(key) or {})` covers that case. For deeper paths, a small
helper is clearer.

```python
service_config: dict[str, Any] = {
    "db": {"host": "localhost", "port": 5432},
    "cache": None,
}
print(f"{service_config.get('db', {}).get('port')=}")
print(f"{service_config.get('queue', {}).get('url')=}")
none_value_result = raised_error_name(
    lambda: service_config.get("cache", {}).get("ttl")
)
print(f"key present with None: {none_value_result}")
print(f"{(service_config.get('cache') or {}).get('ttl')=}")


def nested_get(
    mapping: Mapping[str, Any], *keys: str, default: object = None
) -> object:
    """Follow keys through nested mappings; default if any step is missing."""
    current_value: object = mapping
    for key in keys:
        if not isinstance(current_value, Mapping) or key not in current_value:
            return default
        current_value = current_value[key]
    return current_value


print(f"{nested_get(service_config, 'db', 'host')=}")
print(f"{nested_get(service_config, 'cache', 'ttl', default=60)=}")
```

```text
service_config.get('db', {}).get('port')=5432
service_config.get('queue', {}).get('url')=None
key present with None: AttributeError
(service_config.get('cache') or {}).get('ttl')=None
nested_get(service_config, 'db', 'host')='localhost'
nested_get(service_config, 'cache', 'ttl', default=60)=60
```

### Merging with precedence

Later sources win in both `{**a, **b}` and `a | b`, so list the sources from lowest
to highest priority. Both build a new dict. A `ChainMap` (1.6.7) gives the same
lookups without copying, but lists the sources from **highest** priority first.

```python
default_options = {"retries": 3, "timeout": 10, "region": "ap-south-1"}
team_options = {"timeout": 30}
request_options = {"retries": 5}
merged_by_unpacking = {**default_options, **team_options, **request_options}
merged_by_operator = default_options | team_options | request_options
layered_options = ChainMap(request_options, team_options, default_options)
print(f"{merged_by_unpacking=}")
print(f"{merged_by_unpacking == merged_by_operator=}")
print(f"{dict(layered_options) == merged_by_operator=}")
```

```text
merged_by_unpacking={'retries': 5, 'timeout': 30, 'region': 'ap-south-1'}
merged_by_unpacking == merged_by_operator=True
dict(layered_options) == merged_by_operator=True
```

### Filtering with dict comprehensions

A dict comprehension with an `if` keeps the pairs that pass a test. A common case is
an allow-list of keys, for example to strip private fields before returning a record
from an API.

```python
stock_levels = {"rice": 12, "dal": 0, "ghee": 2, "salt": 0}
in_stock = {
    item: quantity for item, quantity in stock_levels.items() if quantity > 0
}
print(f"{in_stock=}")
user_record = {
    "name": "Asha",
    "email": "asha@example.in",
    "password_hash": "x9f3",
}
public_field_names = {"name", "email"}
public_record = {
    key: value
    for key, value in user_record.items()
    if key in public_field_names
}
print(f"{public_record=}")
```

```text
in_stock={'rice': 12, 'ghee': 2}
public_record={'name': 'Asha', 'email': 'asha@example.in'}
```

### Iterating with `items()`

Iterating a dict directly gives only its keys. To get both, iterate `items()` and
unpack each pair in the `for` target (like `for (const [k, v] of Object.entries(o))`).
Add `enumerate` for a running number.

```python
menu_prices = {"dosa": 60, "idli": 40, "vada": 30}
for line_number, (dish, price) in enumerate(menu_prices.items(), start=1):
    print(f"{line_number}. {dish:<6}{price:>5}")
print(f"{sum(menu_prices.values())=}")
```

```text
1. dosa     60
2. idli     40
3. vada     30
sum(menu_prices.values())=130
```

### Converting to and from JSON

A dict of strings, numbers, booleans, `None`, lists and dicts round-trips through the
`json` module. There are three traps:

- **non-string keys become strings**, so the round trip is not equal;
- tuple keys and `Decimal` values raise `TypeError` (pass `default=str` to convert
  unknown values);
- `True` and `None` become `true` and `null`.

```python
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
print(
    "Decimal value: "
    f"{raised_error_name(lambda: json.dumps({'rate': Decimal('1.5')}))}"
)
print(json.dumps({"rate": Decimal("1.5")}, default=str))
```

```text
{"coupon": null, "items": [{"qty": 2, "sku": "TEA"}], "order_id": 1001,
  "paid": true}
json.loads(payload_text) == order_payload=True
int_key_round_trip={'1': 'one', '2': 'two'},
  int_key_round_trip == int_key_dict=False
tuple key: TypeError
Decimal value: TypeError
{"rate": "1.5"}
```

### Key points

| Pattern | Idiom |
| --- | --- |
| Count | `Counter(items)` |
| Group | `defaultdict(list)` or `setdefault` |
| Index by ID | `{row["id"]: row for row in rows}` |
| Invert | `{v: k for k, v in d.items()}` (unique values) |
| Sort by value | `sorted(d.items(), key=...)` |
| Nested read | `(d.get(k) or {}).get(k2)` |
| Merge | `low \| mid \| high` |
| Filter | `{k: v for k, v in d.items() if ...}` |
| JSON | Keys become strings |

## 1.6.13 Classic data structures with built-ins

Python has no `Stack`, `Queue` or `Graph` classes in the core language, because the
built-in containers already do the job. This section builds the classic structures
from `list`, `deque`, `dict`, `set` and the `heapq` module.

### Stack (LIFO): a `list` with `append` / `pop`

Both operations work at the end of the list, so both are O(1). JavaScript arrays use
the same `push` / `pop` pattern. The bracket checker is the textbook stack exercise:
push each opening bracket, and check that each closing bracket matches the most
recent one.

```python
def brackets_balanced(text: str) -> bool:
    """Return True if every (, [ and { in text is closed in the right order."""
    closing_to_opening = {")": "(", "]": "[", "}": "{"}
    open_brackets: list[str] = []
    for character in text:
        if character in "([{":
            open_brackets.append(character)
        elif character in closing_to_opening:
            if (
                not open_brackets
                or open_brackets.pop() != closing_to_opening[character]
            ):
                return False
    return not open_brackets


undo_stack = ["type 'a'", "type 'b'", "bold"]
print(f"{undo_stack[-1]=} (peek), {undo_stack.pop()=}, {undo_stack=}")
print(
    f"{brackets_balanced('{[()]}')=}, "
    f"{brackets_balanced('([)]')=}, "
    f"{brackets_balanced('((')=}"
)
```

```text
undo_stack[-1]='bold' (peek), undo_stack.pop()='bold',
  undo_stack=["type 'a'", "type 'b'"]
brackets_balanced('{[()]}')=True, brackets_balanced('([)]')=False,
  brackets_balanced('((')=False
```

### FIFO queue: a `deque` with `append` / `popleft`

Both ends are O(1) on a deque, so a deque is the right queue for single-threaded
code. (For queues shared between threads, the `queue` module adds locking.)

```python
support_queue: deque[str] = deque()
for ticket_title in ["login fails", "refund request", "typo on page"]:
    support_queue.append(ticket_title)
while support_queue:
    print(f"serving: {support_queue.popleft()}")
```

```text
serving: login fails
serving: refund request
serving: typo on page
```

### Priority queue: `heapq` on a list

`heapq` keeps a plain list in **min-heap** order: a binary tree packed into the list,
where every parent is smaller than its children. `heappush` and `heappop` are
O(log n), and `heap[0]` is always the smallest item. Push tuples of
`(priority, sequence_number, task)`: tuples compare item by item, so the sequence
number breaks ties in arrival order and stops Python from ever comparing two tasks
(which might not be comparable). `heapify` turns an existing list into a heap in
O(n), and `nsmallest` / `nlargest` answer top-k questions.

```python
pending_jobs: list[tuple[int, int, str]] = []
incoming_jobs = [
    (3, "send newsletter"),
    (1, "capture payment"),
    (2, "resize image"),
    (1, "refund"),
]
for sequence_number, (priority, job_name) in enumerate(incoming_jobs):
    heapq.heappush(pending_jobs, (priority, sequence_number, job_name))
print(f"{pending_jobs[0]=}  (smallest priority first)")
while pending_jobs:
    priority, _sequence_number, job_name = heapq.heappop(pending_jobs)
    print(f"priority {priority}: {job_name}")
response_times_ms = [120, 45, 300, 80, 95]
heapq.heapify(response_times_ms)
print(
    f"{response_times_ms[0]=}, "
    f"{heapq.nlargest(2, [120, 45, 300, 80, 95])=}"
)
```

```text
pending_jobs[0]=(1, 1, 'capture payment')  (smallest priority first)
priority 1: capture payment
priority 1: refund
priority 2: resize image
priority 3: send newsletter
response_times_ms[0]=45, heapq.nlargest(2, [120, 45, 300, 80, 95])=[300, 120]
```

*New in 3.14:* `heapq` gained public max-heap functions (`heapify_max`,
`heappush_max`, `heappop_max`, and more), so a max-heap no longer needs negated
numbers.

```python
if sys.version_info >= (3, 14):
    bid_amounts = [120, 450, 300, 80]
    heapq.heapify_max(bid_amounts)
    heapq.heappush_max(bid_amounts, 500)
    print(
        f"{heapq.heappop_max(bid_amounts)=}, "
        f"{heapq.heappop_max(bid_amounts)=}"
    )
else:
    print(
        "max-heap functions need Python 3.14+; "
        "push negated values on older versions"
    )
```

```text
heapq.heappop_max(bid_amounts)=500, heapq.heappop_max(bid_amounts)=450
```

### Graphs, BFS and visited sets

An **adjacency list** maps each node to its neighbours: `dict[str, list[str]]`.
Breadth-first search (BFS) explores in rings of increasing distance from the start,
so the first time it reaches the goal is along a shortest path (fewest edges). It
needs a FIFO queue (a `deque`) and a `visited` set that stops it from queueing a node
twice. O(1) membership is the reason `visited` is a set and not a list. `came_from`
records how each node was reached, so the path can be rebuilt backwards at the end.

```text
Airport --- Central --- Market
   |           |           |
  Park      Stadium     Harbour
   |                       |
 Museum -------------------+
```

```python
metro_lines: dict[str, list[str]] = {
    "Airport": ["Central", "Park"],
    "Central": ["Airport", "Market", "Stadium"],
    "Park": ["Airport", "Museum"],
    "Market": ["Central", "Harbour"],
    "Stadium": ["Central"],
    "Museum": ["Park", "Harbour"],
    "Harbour": ["Market", "Museum"],
}


def bfs_shortest_path(
    graph: dict[str, list[str]], start: str, goal: str
) -> list[str] | None:
    """Return a fewest-edges path from start to goal, or None."""
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
```

```text
bfs_shortest_path(metro_lines, 'Airport', 'Harbour')=
  ['Airport', 'Central', 'Market', 'Harbour']
bfs_shortest_path(metro_lines, 'Stadium', 'Museum')=
  ['Stadium', 'Central', 'Airport', 'Park', 'Museum']
bfs_shortest_path(metro_lines, 'Airport', 'Moon')=None
```

### DFS with an explicit stack

Depth-first search (DFS) swaps the queue for a stack (a `list`), so it follows one
branch as deep as it goes before backtracking. Pushing the neighbours in reverse
makes the visit order match the recursive version, and an explicit stack avoids
Python's recursion limit (Unit 1.10).

```python
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
print(
    f"{len(dfs_order(metro_lines, 'Airport')) == len(metro_lines)=}"
    "  (all reachable)"
)
```

```text
dfs_order(metro_lines, 'Airport')=['Airport', 'Central', 'Market', 'Harbour',
  'Museum', 'Park', 'Stadium']
len(dfs_order(metro_lines, 'Airport')) == len(metro_lines)=True  (all reachable)
```

### A trie as nested dicts

A trie (prefix tree) stores words letter by letter: each level maps one character to
the next level, and a special key marks the end of a word. Prefix search walks down
the prefix, then collects every word below that point. `setdefault` builds missing
levels in one line.

```python
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
print(
    f"{trie_words_with_prefix(city_trie, 'pu')=}, "
    f"{trie_words_with_prefix(city_trie, 'x')=}"
)
print(json.dumps(city_trie["g"]))
```

```text
trie_words_with_prefix(city_trie, 'pu')=['pune', 'punjab', 'puri'],
  trie_words_with_prefix(city_trie, 'x')=[]
{"o": {"a": {"$": true}}}
```

### A singly linked list

This is a preview of Phase 2, where classes are covered properly. Each node holds a
value and a reference to the next node. Pushing to the front and inserting after a
node you already hold are O(1); finding the n-th item is O(n). In everyday Python a
`list` or `deque` is almost always the better choice; the point here is to see the
pointer structure. The annotation `LinkedListNode | None` inside the class works
unquoted because annotations are evaluated lazily since 3.14 (PEP 649).

```python
class LinkedListNode:
    """One node of a singly linked list."""

    def __init__(
        self, value: str, next_node: LinkedListNode | None = None
    ) -> None:
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


playlist_head = LinkedListNode(
    "intro", LinkedListNode("verse", LinkedListNode("chorus"))
)
playlist_head = LinkedListNode("countdown", playlist_head)  # O(1) push front
verse_node = playlist_head.next_node.next_node
# O(1) insert after a node we already hold:
verse_node.next_node = LinkedListNode("bridge", verse_node.next_node)
print(f"{linked_list_values(playlist_head)=}")
```

```text
linked_list_values(playlist_head)=
  ['countdown', 'intro', 'verse', 'bridge', 'chorus']
```

### Big-O summary

Average case, for every operation used in this section (*n* items, *k* items
involved, *V* nodes and *E* edges).

| Operation | Built-in used | Cost |
| --- | --- | --- |
| Stack push | `list.append` | O(1) amortized |
| Stack pop / peek | `list.pop()` / `items[-1]` | O(1) |
| Queue enqueue | `deque.append` | O(1) |
| Queue dequeue | `deque.popleft` | O(1) |
| Queue dequeue (wrong tool) | `list.pop(0)` | O(n) |
| Priority push / pop | `heappush` / `heappop` | O(log n) |
| Priority peek | `heap[0]` | O(1) |
| Heap build | `heapify` | O(n) |
| Top k | `nlargest(k, …)` | O(n log k) |
| Visited add / check | `set.add` / `in` | O(1) |
| Graph neighbours | `graph[node]` | O(1) find, O(degree) scan |
| BFS / DFS traversal | `deque` / `list` + `set` | O(V + E) |
| Trie insert | nested `dict` + `setdefault` | O(word length) |
| Trie prefix lookup | nested `dict` | O(prefix + matches) |
| Linked list push front | node objects | O(1) |
| Linked list insert after held node | node objects | O(1) |
| Linked list find n-th / search | walk `next_node` | O(n) |

## 1.6.14 Real-world use cases

The structures in this unit show up constantly in production code. Each example
below is small but realistic.

### `dict`: parsed JSON payloads, lookup tables, caches

A webhook body parses into nested dicts. A constant dict maps country codes to
names. A dict keyed by the call's arguments caches an expensive computation
(`functools.cache`, Unit 1.12, does this for you).

```python
webhook_body = (
    '{"event": "payment.captured", '
    '"payment": {"id": "pay_29", "amount": 49900}}'
)
webhook_payload = json.loads(webhook_body)
amount_in_rupees = Decimal(webhook_payload["payment"]["amount"]) / 100
print(f"{webhook_payload['event']=}, {amount_in_rupees=}")

COUNTRY_NAMES = {"IN": "India", "US": "United States", "JP": "Japan"}
print(
    f"{COUNTRY_NAMES.get('JP', 'unknown')=}, "
    f"{COUNTRY_NAMES.get('XX', 'unknown')=}"
)

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
```

```text
webhook_payload['event']='payment.captured', amount_in_rupees=Decimal('499')
COUNTRY_NAMES.get('JP', 'unknown')='Japan',
  COUNTRY_NAMES.get('XX', 'unknown')='unknown'
  (slow lookup for ('USD', 'INR'))
exchange_rate('USD', 'INR')=Decimal('83.25')
exchange_rate('USD', 'INR')=Decimal('83.25')  (served from the cache)
```

### `dict`: config objects, dispatch tables, records by ID

A **dispatch table** maps a request to a handler function and replaces a long
`if`/`elif` chain. Functions are ordinary objects in Python, so they can be dict
values. Web frameworks (Phase 6) route requests this way.

```python
server_config = {
    "debug": False,
    "workers": 4,
    "allowed_hosts": ["shop.example.in"],
}
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
```

```text
201 Created: GHEE
200 OK: ['DAL', 'GHEE', 'TEA']
404 Not Found
server_config['workers']=4, products_by_sku['GHEE']['price']=640
```

### `set`: deduplication, permissions, tags, dataset comparison

Normalise before deduplicating (as `normalize_email` did in 1.4.7). Permission checks
become subset tests, a tag match is an intersection, and comparing two exports of
user IDs is one subtraction in each direction. The visited sets in 1.6.13 are the
graph-traversal use.

```python
signup_emails = [
    "Asha@Example.in",
    "ravi@example.in",
    " asha@example.in",
    "RAVI@example.in",
]
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
```

```text
sorted(unique_emails)=['asha@example.in', 'ravi@example.in']
'delete' in ROLE_PERMISSIONS['editor']=False
ROLE_PERMISSIONS['viewer'] <= ROLE_PERMISSIONS['admin']=True
sorted(post_tags & followed_tags)=['python']  (why this post is in the feed)
users_in_billing - users_in_crm={105, 102},
  users_in_crm - users_in_billing={104}
visited set: see bfs_shortest_path and dfs_order in 1.6.13
```

### `frozenset` / `frozendict`: cache keys, sets of sets, immutable config

A search filter given as a dict cannot be a cache key, but
`frozenset(filters.items())` can (or `frozendict(filters)` on 3.15), and the same
filters in any order hit the same entry.

```python
search_cache: dict[frozenset[tuple[str, str]], list[str]] = {}
first_filters = {"city": "Pune", "cuisine": "south indian"}
search_cache[frozenset(first_filters.items())] = ["Dosa Corner", "Idli House"]
same_filters_reordered = {"cuisine": "south indian", "city": "Pune"}
print(f"{search_cache[frozenset(same_filters_reordered.items())]=}")

ingredient_combos = {
    frozenset({"rice", "dal"}),
    frozenset({"dal", "rice"}),
    frozenset({"rice"}),
}
print(
    f"{len(ingredient_combos)=}"
    "  (a set of sets; order inside each set ignored)"
)

if sys.version_info >= (3, 15):
    FEATURE_FLAGS = frozendict(new_checkout=True, dark_mode=False)
    reordered_flags = frozendict(dark_mode=False, new_checkout=True)
    print(f"{FEATURE_FLAGS['new_checkout']=}")
    same_hash = hash(FEATURE_FLAGS) == hash(reordered_flags)
    print(f"usable as one cache key: {same_hash}")
else:
    print("frozendict needs Python 3.15; skipped")
```

```text
search_cache[frozenset(same_filters_reordered.items())]=
  ['Dosa Corner', 'Idli House']
len(ingredient_combos)=2  (a set of sets; order inside each set ignored)
FEATURE_FLAGS['new_checkout']=True
usable as one cache key: True
```

### `deque`: BFS queues, sliding windows, last N events

`bfs_shortest_path` in 1.6.13 already uses a deque as its queue. A `maxlen` deque
gives a moving average over the last few readings, and an "N most recent events"
history.

```python
print(
    f"{bfs_shortest_path(metro_lines, 'Park', 'Market')=}"
    "  (a deque inside)"
)

latency_window: deque[int] = deque(maxlen=3)
for latency_ms in [120, 80, 100, 400, 90]:
    latency_window.append(latency_ms)
    moving_average = sum(latency_window) / len(latency_window)
    print(f"latest {latency_ms:>3} ms → moving average {moving_average:6.1f}")

recent_events: deque[str] = deque(maxlen=2)
for event_name in ["login", "view cart", "add item", "checkout"]:
    recent_events.append(event_name)
print(f"{list(recent_events)=}")
```

```text
bfs_shortest_path(metro_lines, 'Park', 'Market')=
  ['Park', 'Airport', 'Central', 'Market']  (a deque inside)
latest 120 ms → moving average  120.0
latest  80 ms → moving average  100.0
latest 100 ms → moving average  100.0
latest 400 ms → moving average  193.3
latest  90 ms → moving average  196.7
list(recent_events)=['add item', 'checkout']
```

### `deque`: rate-limiter timestamps

A sliding-window rate limiter keeps the times of recent requests. On each request it
drops timestamps older than the window from the left, then allows the request if
fewer than `limit` remain. The times here are fixed numbers, so the output is
deterministic.

```python
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
    allowed = allow_request(
        client_request_times, request_time, limit=3, window_seconds=1.0
    )
    print(
        f"t={request_time:.1f}s: "
        f"{'allowed' if allowed else 'rejected (429)'}"
    )
```

```text
t=0.0s: allowed
t=0.2s: allowed
t=0.4s: allowed
t=0.6s: rejected (429)
t=1.1s: allowed
t=1.3s: allowed
```

### `Counter`: word frequencies, page views, inventory

```python
review_text = (
    "Great dosa. Great chutney! The dosa was crisp; the chutney was fresh."
)
word_frequencies = Counter(re.findall(r"[a-z]+", review_text.lower()))
print(f"{word_frequencies.most_common(3)=}")

request_paths = ["/home", "/product/7", "/home", "/cart", "/product/7", "/home"]
print(f"{Counter(request_paths).most_common(2)=}")

inventory = Counter(tea=40, rice=25)
inventory += Counter(tea=10, ghee=12)  # shipment received
inventory -= Counter(rice=25)  # sold out: the zero count is dropped
print(f"{inventory=}, {inventory.total()=}")
```

```text
word_frequencies.most_common(3)=[('great', 2), ('dosa', 2), ('chutney', 2)]
Counter(request_paths).most_common(2)=[('/home', 3), ('/product/7', 2)]
inventory=Counter({'tea': 50, 'ghee': 12}), inventory.total()=62
```

### `defaultdict`: grouping and adjacency lists

Grouping records by a field (here invoices by month; grouping orders by customer is
Lab 1.6, exercise 1) and building an adjacency list from an edge list are the same
three lines.

```python
invoices = [
    ("2026-09", 1200),
    ("2026-10", 800),
    ("2026-09", 450),
    ("2026-10", 300),
]
amounts_by_month: defaultdict[str, list[int]] = defaultdict(list)
for month, amount in invoices:
    amounts_by_month[month].append(amount)
monthly_totals = {
    month: sum(amounts) for month, amounts in amounts_by_month.items()
}
print(f"{monthly_totals=}")

road_edges = [("Pune", "Mumbai"), ("Pune", "Nashik"), ("Mumbai", "Goa")]
road_graph: defaultdict[str, list[str]] = defaultdict(list)
for city_a, city_b in road_edges:
    road_graph[city_a].append(city_b)
    road_graph[city_b].append(city_a)
print(f"{dict(road_graph)=}")
```

```text
monthly_totals={'2026-09': 1650, '2026-10': 1100}
dict(road_graph)={'Pune': ['Mumbai', 'Nashik'], 'Mumbai': ['Pune', 'Goa'],
  'Nashik': ['Pune'], 'Goa': ['Mumbai']}
```

### `OrderedDict` for LRU caches; `ChainMap` for layered config

An LRU cache needs exactly two `OrderedDict` moves: `move_to_end` on every hit and
`popitem(last=False)` when full (Lab 1.6, exercise 4, wraps them in a class). For
configuration, `argparse` with `argument_default=argparse.SUPPRESS` leaves unset
options out of its result entirely, so they fall through to the next layer of the
ChainMap: command line > environment > defaults.

```python
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
settings = ChainMap(
    cli_settings,
    env_settings,
    {"port": 8000, "debug": False, "host": "0.0.0.0"},
)
print(f"{dict(settings)=}")
```

```text
evicted /cart
list(page_cache)=['/home', '/pay']
dict(settings)={'port': 9000, 'debug': True, 'host': '0.0.0.0'}
```

### Key points

| Container | Typical production use |
| --- | --- |
| `dict` | JSON, lookups, caches, dispatch, records by ID |
| `set` | Dedupe, permissions, tags, dataset diffs |
| `frozenset` / `frozendict` | Cache keys, sets of sets, constants |
| `deque` | BFS, sliding windows, rate limiting |
| `Counter` | Frequencies, analytics, tallies |
| `defaultdict` | Grouping, adjacency lists |
| `OrderedDict` / `ChainMap` | LRU caches / layered config |

## Lab 1.6

Five exercises on one small order dataset. In the notebook, each exercise has a stub
function and a check cell that prints `PASS` or `FAIL` for every test case. Try each
exercise before opening its solution.

The shared data: an `Order` record, eight `SAMPLE_ORDERS`, and `PRODUCT_CATALOG`, a
`frozendict` of SKU → unit price (a read-only `MappingProxyType` on interpreters
older than 3.15). `SOAP-3PK` is deliberately missing from the catalog.

```python
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
```

```text
len(SAMPLE_ORDERS)=8, type(PRODUCT_CATALOG).__name__='frozendict'
```

### Exercise 1 — `group_orders_by_customer(orders)`

Group orders by customer with a `defaultdict(list)`. Return a **plain `dict`**, so
that looking up a missing customer raises `KeyError` instead of creating an empty
entry. Customers must appear in the order they are first seen, and each customer's
orders must stay in input order.

Signature: `group_orders_by_customer(orders: Iterable[Order]) -> dict[str, list[Order]]`

Test cases:

- order IDs per customer: `asha` → `[1001, 1003, 1008]`, `ravi` → `[1002, 1005]`,
  `meena` → `[1004, 1007]`, `john` → `[1006]`;
- customers in first-seen order: `['asha', 'ravi', 'meena', 'john']`;
- the result's type is exactly `dict`;
- `result["zoe"]` raises `KeyError`;
- it accepts an iterator (`iter(SAMPLE_ORDERS[:2])` gives `['asha', 'ravi']`);
- no orders gives `{}`.

Hints: a single pass is enough, since dicts keep insertion order; `dict(...)` of a
defaultdict makes a plain copy.

<details><summary>Solution</summary>

```python
def group_orders_by_customer(
    orders: Iterable[Order],
) -> dict[str, list[Order]]:
    """Return {customer: [their orders in input order]} as a plain dict."""
    orders_by_customer: defaultdict[str, list[Order]] = defaultdict(list)
    for order in orders:
        orders_by_customer[order.customer].append(order)
    return dict(orders_by_customer)
```

Iterating once works with any iterable, including a one-shot iterator. The
defaultdict removes the "first order for this customer?" check, and converting to a
plain `dict` at the end restores normal `KeyError` behaviour for callers.

</details>

### Exercise 2 — `top_k_words(text, k)`

Return the `k` most frequent words as `(word, count)` pairs. Words are compared
**case-insensitively** (use `casefold`) and **ignoring punctuation**: a word is a run
of letters or digits, `re.findall(r"[^\W_]+", ...)`. Sort by count descending, then
break **ties alphabetically**. `k <= 0` gives `[]`.

> **Note:** `Counter.most_common` breaks ties by first appearance, not
> alphabetically, so it is not enough on its own.

Test cases, with `nursery_text = "The cat and the hat. THE CAT sat; a bat sat!"`:

| Call | Expected |
| --- | --- |
| `top_k_words(nursery_text, 3)` | `[('the', 3), ('cat', 2), ('sat', 2)]` |
| `top_k_words(nursery_text, 5)` | adds `('a', 1), ('and', 1)` |
| `len(top_k_words(nursery_text, 50))` | `7` |
| `top_k_words(nursery_text, 0)` | `[]` |
| `top_k_words("", 3)` | `[]` |
| `top_k_words("Café café CAFÉ, tea", 1)` | `[('café', 3)]` |
| `top_k_words("snake_case snake", 1)` | `[('snake', 2)]` |

Hints: `[^\W_]` means "a word character that is not an underscore", so
`snake_case` splits into two words; a sort key of `(-count, word)` gives
"count descending, then word ascending" in one `sorted` call.

<details><summary>Solution</summary>

```python
WORD_PATTERN = re.compile(r"[^\W_]+")


def top_k_words(text: str, k: int) -> list[tuple[str, int]]:
    """Return the k most frequent words, ties broken alphabetically."""
    if k <= 0:
        return []
    word_counts = Counter(WORD_PATTERN.findall(text.casefold()))
    ranked_words = sorted(
        word_counts.items(), key=lambda pair: (-pair[1], pair[0])
    )
    return ranked_words[:k]
```

`casefold` is a stronger `lower` designed for caseless matching (Unit 1.4), and the
negated count turns an ascending sort into "highest count first" while the word
still sorts ascending. Slicing past the end of a list is safe, so a large `k` simply
returns every word.

</details>

### Exercise 3 — `merge_configs(defaults, env, cli)`

Return a `ChainMap` where command-line values beat environment values, which beat
defaults. A `None` value in `cli` means "flag not given" and must not hide the lower
layers. Writes to the result must not change any of the three input dicts.

The check uses these inputs:

```python
default_config = {
    "host": "localhost",
    "port": 8000,
    "debug": False,
    "log_level": "INFO",
}
env_config = {"port": 9000, "log_level": "WARNING"}
cli_config = {"debug": True, "port": None}
```

Test cases:

- the result's type is `ChainMap`;
- `dict(result)` is
  `{"host": "localhost", "port": 9000, "debug": True, "log_level": "WARNING"}`;
- `result["port"]` is `9000` (the CLI's `None` is ignored);
- writing `result["host"] = "example.in"` and `result["timeout"] = 30` leaves all
  three inputs unchanged;
- `dict(merge_configs({"a": 1}, {}, {}))` is `{"a": 1}`.

Hints: filter the `None` values out of `cli` with a dict comprehension; writes go to
`maps[0]`, so put a fresh empty dict first in the chain.

<details><summary>Solution</summary>

```python
def merge_configs(
    defaults: Mapping[str, object],
    env: Mapping[str, object],
    cli: Mapping[str, object],
) -> ChainMap[str, object]:
    """Layer cli > env > defaults; None in cli means "not given"."""
    given_cli_values = {
        key: value for key, value in cli.items() if value is not None
    }
    return ChainMap({}, given_cli_values, env, defaults)
```

The comprehension builds a new dict, so the caller's `cli` is never modified. The
leading `{}` absorbs every write, which keeps all three inputs (and the filtered
copy) untouched.

</details>

### Exercise 4 — `LRUCache(capacity)`

Build a least-recently-used cache on an `OrderedDict`:

- `get(key, default=None)`: return the value and mark the key most recently used;
  return `default` on a miss.
- `put(key, value)`: insert or update, mark the key most recently used, and if the
  cache is now over capacity evict the **least** recently used key.
- `len(cache)` and `key in cache` (membership does **not** change recency).
- `capacity < 1` raises `ValueError`.

Test cases (each starts from a fresh `LRUCache(2)`):

- put `a`, put `b`, get `a`, put `c`: then `get("a")` was `1`, `get("b")` is `None`,
  `get("c")` is `3`, `len` is `2`, `"a" in cache` is `True`;
- put `a`, put `b`, put `a` again with `10`, put `c`: `get("a")` is `10`, `"b"` was
  evicted, `len` is `2`;
- put `a`, put `b`, test `"a" in cache`, put `c`: `"a"` was evicted, because `in`
  does not refresh;
- `LRUCache(1).get("x", "fallback")` is `"fallback"`;
- `LRUCache(0)` raises `ValueError`.

Hints: keep the most recently used key at the **end** of the OrderedDict; the front
is then always the eviction candidate for `popitem(last=False)`. `__len__` and
`__contains__` are the special methods behind `len()` and `in` (Phase 2 covers them
in depth).

<details><summary>Solution</summary>

```python
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
        """Store value, evicting the least recently used key if needed."""
        self._entries[key] = value
        self._entries.move_to_end(key)
        if len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries
```

Updating an existing key keeps its old position in an OrderedDict, so `put` calls
`move_to_end` explicitly. Every operation is O(1). In real code,
`functools.lru_cache` (Unit 1.12) gives you this for function results.

</details>

### Exercise 5 — order-analytics pipeline

Write `analyze_orders(orders, catalog)` returning a dict with exactly these keys:

| Key | Value | Build it with |
| --- | --- | --- |
| `revenue_by_customer` | quantity × price, catalog SKUs only | `defaultdict(Decimal)` |
| `top_skus` | 3 best-selling catalog SKUs by units | `Counter.most_common(3)` |
| `unique_customer_count` | distinct customers, all orders | `set` |
| `recent_order_ids` | last 5 order IDs, oldest first | `deque(maxlen=5)` |
| `unknown_skus` | SKUs missing from the catalog, sorted | `set`, then `sorted` |

Orders with an unknown SKU count towards customers and recent orders, but not towards
revenue or `top_skus`. Return plain `dict` and `list` values, not the helper
containers.

Expected results for `analyze_orders(SAMPLE_ORDERS, PRODUCT_CATALOG)`:

- `revenue_by_customer`: `asha` → `Decimal("1462.50")`, `ravi` →
  `Decimal("774.50")`, `meena` → `Decimal("1798.00")`, as a plain `dict`;
- `top_skus`: `[("TEA-500G", 6), ("RICE-5KG", 3), ("DAL-1KG", 2)]`;
- `unique_customer_count`: `4`;
- `recent_order_ids`: `[1004, 1005, 1006, 1007, 1008]`;
- `unknown_skus`: `["SOAP-3PK"]`;
- with no orders, every value is empty (`{}`, `[]`, `0`, `[]`, `[]`).

Hints: `Decimal()` with no argument is `Decimal('0')`, so `Decimal` works as a
defaultdict factory; record the customer and the order ID *before* skipping an
unknown SKU with `continue`.

<details><summary>Solution</summary>

```python
def analyze_orders(
    orders: Iterable[Order], catalog: Mapping[str, Decimal]
) -> dict[str, object]:
    """Summarise orders: revenue, top SKUs, customers, recent IDs, unknowns."""
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
        revenue_by_customer[order.customer] += (
            catalog[order.sku] * order.quantity
        )
        units_by_sku[order.sku] += order.quantity
    return {
        "revenue_by_customer": dict(revenue_by_customer),
        "top_skus": units_by_sku.most_common(3),
        "unique_customer_count": len(customers),
        "recent_order_ids": list(recent_order_ids),
        "unknown_skus": sorted(unknown_skus),
    }
```

One pass feeds five containers, each chosen for its job. `john` only ordered the
unknown SKU, so he counts as a customer but has no revenue entry. Converting at the
end (`dict(...)`, `list(...)`, `sorted(...)`) keeps the helper types out of the
public result.

</details>

Running the notebook's check cells against these reference solutions prints:

```text
Exercise 1 — group_orders_by_customer
PASS  order ids per customer
PASS  customers in first-seen order
PASS  returns a plain dict
PASS  missing customer raises
PASS  accepts an iterator
PASS  no orders
6/6 checks passed

Exercise 2 — top_k_words
PASS  top 3
PASS  ties alphabetical
PASS  k larger than vocabulary
PASS  k = 0
PASS  empty text
PASS  caseless and unicode
PASS  underscore splits words
7/7 checks passed

Exercise 3 — merge_configs
PASS  returns a ChainMap
PASS  precedence cli > env > defaults
PASS  None in cli is ignored
PASS  writes leave inputs alone
PASS  empty layers
5/5 checks passed

Exercise 4 — LRUCache
PASS  get refreshes recency
PASS  put updates and refreshes
PASS  in does not refresh
PASS  get default on miss
PASS  capacity 0 raises
5/5 checks passed

Exercise 5 — analyze_orders
PASS  revenue by customer
PASS  top 3 SKUs by units
PASS  unique customers
PASS  last 5 order ids
PASS  unknown SKUs
PASS  revenue is a plain dict
PASS  no orders
7/7 checks passed
```

## Recap

| Concept | Takeaway | JavaScript equivalent |
| --- | --- | --- |
| `dict` internals | Sparse indices + dense entries; ordered; O(1) | `Map` |
| Probing, resizing | Perturbed probe; ≤ 2/3 full; rare O(n) resize | — |
| Key-sharing dicts | Instances share one key table (PEP 412) | V8 hidden classes |
| Hashable | Stable `__hash__` that agrees with `__eq__` | `Map` uses SameValueZero |
| `1 == 1.0 == True` | One key: first key kept, last value wins | `obj[1]` vs `obj["1"]` collide |
| String hashes | Per-process SipHash key; `PYTHONHASHSEED` | — |
| Access | `d[k]` raises; `get`, `setdefault`, `in` | `obj[k]` is `undefined` |
| Merge | `\|`, `\|=`, `{**a, **b}`, `update`; right wins | `{...a, ...b}` |
| Views | Live; keys and items are set-like | `Object.keys()` snapshot |
| `dict.fromkeys` | Every key shares one value object | `Array(n).fill([])` |
| Resize while iterating | `RuntimeError`; loop over `list(d)` | Silently allowed |
| `SimpleNamespace` | Attribute access over a dict | Plain object |
| `frozendict` | Immutable, hashable (3.15) | `Object.freeze` (not a key) |
| `MappingProxyType` | Read-only live view | — |
| `set` / `frozenset` | `\| & - ^`; methods take iterables | `Set` (+ ES2025 methods) |
| `deque` | O(1) both ends; `maxlen` ring buffer | `shift()` is O(n) |
| `Counter` | Counts, `most_common`, `total`, maths | `reduce` into an object |
| `defaultdict` | Factory runs on a missing-key read | `(m[k] ??= [])` |
| `OrderedDict` | `move_to_end`, `popitem(last=False)` | `Map` delete + set |
| `ChainMap` | Layered lookups, no copying | `Object.assign` (copies) |
| `heapq` | Min-heap on a list; max-heap API in 3.14 | No built-in |
| JSON | Non-string keys become strings | `JSON.stringify` |

## Further reading

- [Mapping types — `dict`](https://docs.python.org/3/library/stdtypes.html#mapping-types-dict)
- [Set types — `set`, `frozenset`](https://docs.python.org/3/library/stdtypes.html#set-types-set-frozenset)
- [`frozendict`](https://docs.python.org/3.15/library/stdtypes.html#frozendict)
- [`collections` — container datatypes](https://docs.python.org/3/library/collections.html)
- [`heapq` — heap queue algorithm](https://docs.python.org/3/library/heapq.html)
- [`types` — `MappingProxyType` and `SimpleNamespace`](https://docs.python.org/3/library/types.html)
- [`object.__hash__`](https://docs.python.org/3/reference/datamodel.html#object.__hash__)
- [`PYTHONHASHSEED`](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONHASHSEED)
- [`json` — JSON encoder and decoder](https://docs.python.org/3/library/json.html)
- [PEP 412 — Key-sharing dictionary](https://peps.python.org/pep-0412/)
- [PEP 456 — Secure and interchangeable hash algorithm](https://peps.python.org/pep-0456/)
- [PEP 468 — Preserving keyword argument order](https://peps.python.org/pep-0468/)
- [PEP 584 — Add union operators to dict](https://peps.python.org/pep-0584/)
- [PEP 649 — Deferred evaluation of annotations](https://peps.python.org/pep-0649/)
- [PEP 814 — Add frozendict built-in type](https://peps.python.org/pep-0814/)

[← Previous](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md) · [Index](README.md) · [Next →](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md)
